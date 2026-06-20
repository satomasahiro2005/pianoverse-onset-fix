# IKMPAK toolkit  --  Pianoverse .pak container reader + WAV onset analysis
# Format (reverse-engineered):
#   "IKMPAK"  u32 version(=2)  u32 entryCount
#   entry[]:  path\0  u64 dataOffset(abs)  u64 dataSize
#   payload:  standard RIFF/WAVE files concatenated (24-bit PCM, 48k, stereo, RX-edited w/ bext+junk)

function Get-PakEntries {
  param([string]$Path, [int]$HeaderBytes = 8MB)
  $fs = [System.IO.File]::OpenRead($Path)
  try {
    $len = [math]::Min($HeaderBytes, $fs.Length)
    $h = New-Object byte[] $len
    $null = $fs.Read($h, 0, $len)
  } finally { $fs.Close() }
  if ([Text.Encoding]::ASCII.GetString($h,0,6) -ne 'IKMPAK') { throw "not IKMPAK: $Path" }
  $ver = [BitConverter]::ToUInt32($h,6)
  $cnt = [BitConverter]::ToUInt32($h,10)
  $p = 14
  $entries = New-Object System.Collections.Generic.List[object]
  for ($e=0; $e -lt $cnt; $e++){
    if ($p -ge $len) { throw "TOC exceeds header buffer at entry $e (raise -HeaderBytes)" }
    $start=$p
    while ($p -lt $len -and $h[$p] -ne 0){ $p++ }
    $path=[Text.Encoding]::ASCII.GetString($h,$start,$p-$start); $p++
    $off=[BitConverter]::ToUInt64($h,$p); $p+=8
    $sz =[BitConverter]::ToUInt64($h,$p); $p+=8
    $entries.Add([pscustomobject]@{ Idx=$e; Off=$off; Size=$sz; Path=$path; Name=($path -split '/')[-1] })
  }
  [pscustomobject]@{ Version=$ver; Count=$cnt; Entries=$entries }
}

# Parse a WAV that sits at $off inside an open stream; reads only the first $PreBytes of payload.
function Read-WavHead {
  param([System.IO.FileStream]$Fs, [long]$Off, [int]$PreBytes = 64KB)
  $Fs.Position = $Off
  $buf = New-Object byte[] $PreBytes
  $got = $Fs.Read($buf,0,$PreBytes)
  if ([Text.Encoding]::ASCII.GetString($buf,0,4) -ne 'RIFF'){ return $null }
  $riff=[BitConverter]::ToUInt32($buf,4)
  $q=12; $fmt=$null; $dataLocal=-1; $dataSz=0; $bextTR=$null
  while ($q+8 -le $got){
    $cid=[Text.Encoding]::ASCII.GetString($buf,$q,4); $csz=[int][BitConverter]::ToUInt32($buf,$q+4); $d=$q+8
    switch ($cid){
      'fmt ' { $fmt=[pscustomobject]@{ Format=[BitConverter]::ToUInt16($buf,$d); Ch=[BitConverter]::ToUInt16($buf,$d+2); SR=[BitConverter]::ToUInt32($buf,$d+4); Bits=[BitConverter]::ToUInt16($buf,$d+14) } }
      'bext' { if ($d+346 -le $got){ $bextTR=[BitConverter]::ToUInt64($buf,$d+338) } }
      'data' { $dataLocal=$d; $dataSz=$csz }
    }
    if ($cid -eq 'data'){ break }
    $q = $d + $csz + ($csz -band 1)
  }
  if (-not $fmt -or $dataLocal -lt 0){ return $null }
  [pscustomobject]@{ Fmt=$fmt; DataAbs=($Off+$dataLocal); DataSize=$dataSz; BextTimeRef=$bextTR; Pre=$buf; PreDataLocal=$dataLocal; PreGot=$got }
}

# Onset = first frame whose |sample| (max of channels) exceeds threshold (dBFS).
# Returns onset in ms and peak dBFS, scanning first $ScanMs of the sample.
function Measure-Onset {
  param([System.IO.FileStream]$Fs, $Wav, [double]$ThreshDb = -60, [int]$ScanMs = 120)
  $sr=[int]$Wav.Fmt.SR; $ch=[int]$Wav.Fmt.Ch; $bps=[int]($Wav.Fmt.Bits/8); $frame=$ch*$bps
  $full=[math]::Pow(2,$Wav.Fmt.Bits-1); $thr=$full*[math]::Pow(10,$ThreshDb/20)
  $scanFrames=[math]::Min([int]($sr*$ScanMs/1000), [int]($Wav.DataSize/$frame))
  $need=$scanFrames*$frame
  # reuse prebuffer if it already covers the scan window, else read fresh
  if ($Wav.PreDataLocal -ge 0 -and ($Wav.PreGot - $Wav.PreDataLocal) -ge $need){
    $buf=$Wav.Pre; $base=$Wav.PreDataLocal
  } else {
    $Fs.Position=$Wav.DataAbs; $buf=New-Object byte[] $need; $null=$Fs.Read($buf,0,$need); $base=0
  }
  $onset=-1; $peak=0
  for ($f=0; $f -lt $scanFrames; $f++){
    $mx=0
    for ($c=0; $c -lt $ch; $c++){
      $i=$base+$f*$frame+$c*$bps
      if ($bps -eq 3){ $v=[int]$buf[$i] + ([int]$buf[$i+1]*256) + ([int]$buf[$i+2]*65536); if ($v -band 0x800000){ $v=$v - 0x1000000 } }
      elseif ($bps -eq 2){ $v=[BitConverter]::ToInt16($buf,$i) } else { $v=$buf[$i]-128 }
      $a=[math]::Abs($v); if($a -gt $mx){$mx=$a}
    }
    if($mx -gt $peak){$peak=$mx}
    if($onset -lt 0 -and $mx -ge $thr){ $onset=$f }
  }
  [pscustomobject]@{
    OnsetMs = if($onset -ge 0){ [math]::Round($onset/$sr*1000,3) } else { $null }
    PeakDb  = if($peak -gt 0){ [math]::Round(20*[math]::Log10($peak/$full),1) } else { -999 }
    DurMs   = [math]::Round($Wav.DataSize/$frame/$sr*1000,1)
  }
}

# IKMPAK head-trim repacker.
# For each embedded WAV: detect the tonal-attack foot, trim leading samples so the
# foot sits at a common preroll, then rebuild the .pak with recomputed TOC offsets.
# Streaming (never holds the whole pak in RAM). 24-bit/48k/stereo PCM assumed.

function S24v($d,$i){ $v=[int]$d[$i] + ([int]$d[$i+1]*256) + ([int]$d[$i+2]*65536); if($v -band 0x800000){ $v=$v-0x1000000 }; $v }

# Find data chunk + fmt inside a WAV buffer ($buf) of length $len starting at 0.
function Get-WavLayout($buf,$len){
  if([Text.Encoding]::ASCII.GetString($buf,0,4) -ne 'RIFF'){ return $null }
  $q=12; $dataHdr=-1; $dataSize=0; $sr=0;$ch=0;$bits=0
  while($q+8 -le $len){
    $cid=[Text.Encoding]::ASCII.GetString($buf,$q,4); $csz=[int][BitConverter]::ToUInt32($buf,$q+4)
    if($cid -eq 'fmt '){ $ch=[BitConverter]::ToUInt16($buf,$q+8+2); $sr=[BitConverter]::ToUInt32($buf,$q+8+4); $bits=[BitConverter]::ToUInt16($buf,$q+8+14) }
    if($cid -eq 'data'){ $dataHdr=$q; $dataSize=$csz; break }
    $q = $q+8+$csz+($csz -band 1)
  }
  if($dataHdr -lt 0){ return $null }
  [pscustomobject]@{ DataHdr=$dataHdr; DataPayload=$dataHdr+8; DataSize=$dataSize; SR=$sr; Ch=$ch; Bits=$bits }
}

# Detect the perceptual onset frame: first time the short-time envelope reaches
# (peak - AnchorDb). Anchoring on a peak-relative LEVEL (not the noise-floor foot)
# is robust across velocity / pitch / round-robins, where a foot search fails:
# loud bass notes have a lead-in that never drops far below peak, so a foot search
# returns 0 and under-trims. Returns -1 when the sample is silent / never crosses.
function Get-OnsetFrame($buf,$lay,[double]$AnchorDb=-20,[int]$scanMs=400){
  $sr=[int]$lay.SR; $ch=[int]$lay.Ch; $bps=[int]($lay.Bits/8); $frame=$ch*$bps
  $base=$lay.DataPayload
  $totalFrames=[int]($lay.DataSize/$frame)
  $scanFrames=[math]::Min($totalFrames,[int]($sr*$scanMs/1000))
  $step=12                                   # 0.25 ms env buckets
  $nb=[int]($scanFrames/$step)
  if($nb -lt 4){ return -1 }
  $env=New-Object double[] $nb
  $peak=0.0
  for($k=0;$k -lt $nb;$k++){
    $mx=0
    for($j=0;$j -lt $step;$j++){
      $f=$k*$step+$j; $i=$base+$f*$frame
      $a=[math]::Max([math]::Abs((S24v $buf $i)),[math]::Abs((S24v $buf ($i+$bps))))
      if($a -gt $mx){$mx=$a}
    }
    $env[$k]=$mx; if($mx -gt $peak){$peak=$mx}
  }
  if($peak -lt 64){ return -1 }              # essentially silent: signal no-onset
  $tAnchor=$peak*[math]::Pow(10,$AnchorDb/20)
  for($k=0;$k -lt $nb;$k++){ if($env[$k] -ge $tAnchor){ return $k*$step } }
  return -1
}

function Repack-PakTrimmed {
  param([string]$InPak,[string]$OutPak,[double]$PrerollMs=1.5,[double]$AnchorDb=-20,[int]$ScanMs=400)
  . "C:\Users\masahiro\pianoverse-research\pak.ps1"
  $t = Get-PakEntries $InPak
  # build new TOC bytes (paths + placeholder offsets/sizes), same layout/order as input
  $ms=New-Object System.IO.MemoryStream
  $bw=New-Object System.IO.BinaryWriter($ms)
  $bw.Write([Text.Encoding]::ASCII.GetBytes('IKMPAK'))
  $bw.Write([uint32]2); $bw.Write([uint32]$t.Count)
  $tocEntryPos=@()
  foreach($e in $t.Entries){
    $bw.Write([Text.Encoding]::ASCII.GetBytes($e.Path)); $bw.Write([byte]0)
    $tocEntryPos += $ms.Position          # remember where the u64 off/size pair goes
    $bw.Write([uint64]0); $bw.Write([uint64]0)
  }
  $bw.Flush()
  $tocBytes=$ms.ToArray()
  $dataStart=$tocBytes.Length

  $fin=[System.IO.File]::OpenRead($InPak)
  $fout=[System.IO.File]::Open($OutPak,[System.IO.FileMode]::Create,[System.IO.FileAccess]::ReadWrite)
  $fout.Write($tocBytes,0,$tocBytes.Length)
  $report=New-Object System.Collections.Generic.List[object]
  $newMeta=@()
  $cur=[int64]$dataStart
  foreach($e in $t.Entries){
    $sz=[int]$e.Size
    $buf=New-Object byte[] $sz
    $fin.Position=$e.Off; $g=0; while($g -lt $sz){ $r=$fin.Read($buf,$g,$sz-$g); if($r -le 0){break}; $g+=$r }
    $lay=Get-WavLayout $buf $sz
    if(-not $lay){ # not a WAV we understand: copy verbatim
      $fout.Write($buf,0,$sz); $newMeta+=,@($cur,$sz); $cur+=$sz; continue }
    $frame=[int]($lay.Ch*($lay.Bits/8))
    $onset=Get-OnsetFrame $buf $lay $AnchorDb $ScanMs
    $preFrames=[int]($lay.SR*$PrerollMs/1000)
    $trimFrames=if($onset -lt 0){0}else{[math]::Max(0,$onset-$preFrames)}
    $trimBytes=$trimFrames*$frame
    if($trimBytes -ge $lay.DataSize){ $trimBytes=0; $trimFrames=0 }
    $newDataSize=$lay.DataSize-$trimBytes
    # kept header = bytes [0 .. DataPayload)  (RIFF/fmt/bext/junk + data hdr)
    $hdrLen=$lay.DataPayload
    $newWavLen=$hdrLen+$newDataSize
    # patch RIFF size (off 4) and data size (DataHdr+4)
    [Array]::Copy([BitConverter]::GetBytes([uint32]($newWavLen-8)),0,$buf,4,4)
    [Array]::Copy([BitConverter]::GetBytes([uint32]$newDataSize),0,$buf,$lay.DataHdr+4,4)
    $fout.Write($buf,0,$hdrLen)
    $fout.Write($buf,$lay.DataPayload+$trimBytes,$newDataSize)
    $newMeta+=,@($cur,$newWavLen); $cur+=$newWavLen
    $report.Add([pscustomobject]@{ Name=$e.Name; OnsetMs=if($onset -lt 0){''}else{[math]::Round($onset/$lay.SR*1000,3)}; TrimMs=[math]::Round($trimFrames/$lay.SR*1000,3); OldKB=[math]::Round($sz/1KB,1); NewKB=[math]::Round($newWavLen/1KB,1) })
  }
  $fin.Close()
  # write real offsets/sizes into TOC
  for($i=0;$i -lt $t.Count;$i++){
    $fout.Position=$tocEntryPos[$i]
    $fout.Write([BitConverter]::GetBytes([uint64]$newMeta[$i][0]),0,8)
    $fout.Write([BitConverter]::GetBytes([uint64]$newMeta[$i][1]),0,8)
  }
  $fout.Close()
  [pscustomobject]@{ In=$InPak; Out=$OutPak; Entries=$t.Count; OutBytes=$cur; Report=$report }
}

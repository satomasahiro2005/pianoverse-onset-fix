# Onset sweep over Pianoverse .pak sample sets.
# For each sample: read first $WinMs, find window peak, report time to cross
# peak-relative thresholds (-40/-30/-20/-12 dB) and time-to-peak.  24-bit PCM.
param(
  [string[]]$Paks,
  [string]$OutCsv = "C:\Users\masahiro\pianoverse-research\onset.csv",
  [int]$WinMs = 250,
  [string]$RrFilter = 'rr1'   # set '' for all round-robins
)
. "C:\Users\masahiro\pianoverse-research\pak.ps1"

function S24b($d,$i){ $v=[int]$d[$i] + ([int]$d[$i+1]*256) + ([int]$d[$i+2]*65536); if($v -band 0x800000){ $v=$v-0x1000000 }; $v }

$sr=48000; $frame=6; $winFrames=[int]($sr*$WinMs/1000); $need=$winFrames*$frame
$rows = New-Object System.Collections.Generic.List[object]

foreach($pak in $Paks){
  $t = Get-PakEntries $pak
  $mic = Split-Path (Split-Path $pak -Parent) -Leaf      # e.g. "Close 1"
  $fs = [System.IO.File]::OpenRead($pak)
  try {
    foreach($e in $t.Entries){
      if($RrFilter -and $e.Name -notmatch $RrFilter){ continue }
      # locate data payload (header is small; 128 bytes is plenty)
      $fs.Position=$e.Off; $h=New-Object byte[] 128; $null=$fs.Read($h,0,128)
      $q=12;$dataLocal=-1
      while($q+8 -le 128){ $cid=[Text.Encoding]::ASCII.GetString($h,$q,4); $csz=[int][BitConverter]::ToUInt32($h,$q+4); if($cid -eq 'data'){$dataLocal=$q+8;break}; $q=$q+8+$csz+($csz -band 1) }
      if($dataLocal -lt 0){ continue }
      $rd = [math]::Min($need, [int]$e.Size)
      $fs.Position=$e.Off+$dataLocal
      $d=New-Object byte[] $rd; $got=0; while($got -lt $rd){ $r=$fs.Read($d,$got,$rd-$got); if($r -le 0){break}; $got+=$r }
      $nf=[int]($got/$frame)
      # window peak
      $peak=0;$peakF=0
      for($f=0;$f -lt $nf;$f++){ $i=$f*6; $a=[math]::Max([math]::Abs((S24b $d $i)),[math]::Abs((S24b $d ($i+3)))); if($a -gt $peak){$peak=$a;$peakF=$f} }
      if($peak -le 0){ continue }
      # onset crossings relative to window peak
      $cross=@{}
      foreach($db in -40,-30,-20,-12){ $cross[$db]=-1 }
      for($f=0;$f -lt $nf;$f++){
        $i=$f*6; $a=[math]::Max([math]::Abs((S24b $d $i)),[math]::Abs((S24b $d ($i+3))))
        foreach($db in -40,-30,-20,-12){ if($cross[$db] -lt 0 -and $a -ge $peak*[math]::Pow(10,$db/20)){ $cross[$db]=$f } }
        if($cross[-12] -ge 0){ break }
      }
      $note = ($e.Name -split '_')[0]
      $vel  = if($e.Name -match '_v(\d+)_'){[int]$matches[1]}else{0}
      $rows.Add([pscustomobject]@{
        Mic=$mic; Note=$note; Vel=$vel; Name=$e.Name
        PeakDb=[math]::Round(20*[math]::Log10($peak/8388608.0),1)
        T_m40ms = if($cross[-40]-ge 0){[math]::Round($cross[-40]/$sr*1000,3)}else{''}
        T_m30ms = if($cross[-30]-ge 0){[math]::Round($cross[-30]/$sr*1000,3)}else{''}
        T_m20ms = if($cross[-20]-ge 0){[math]::Round($cross[-20]/$sr*1000,3)}else{''}
        T_m12ms = if($cross[-12]-ge 0){[math]::Round($cross[-12]/$sr*1000,3)}else{''}
        TpeakMs = [math]::Round($peakF/$sr*1000,2)
      })
    }
  } finally { $fs.Close() }
  Write-Host "  scanned $mic : running total $($rows.Count)"
}
$rows | Export-Csv -NoTypeInformation -Path $OutCsv
Write-Host "wrote $($rows.Count) rows -> $OutCsv"
$rows

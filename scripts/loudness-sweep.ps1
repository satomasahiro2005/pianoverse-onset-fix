# Per-sample loudness sweep over Pianoverse .pak sets.
# Measures peak dBFS and RMS dBFS over the first $WinMs of each WAV (24-bit PCM),
# to characterise volume variation across round-robins / velocity / pitch.
param(
  [string[]]$Paks,
  [string]$OutCsv,
  [int]$WinMs = 300,
  [string]$RrFilter = ''      # '' = all round-robins
)
if (-not $OutCsv) { $OutCsv = 'loudness.csv' }   # relative to where you run it
. (Join-Path $PSScriptRoot 'pak.ps1')
function S24l($d,$i){ $v=[int]$d[$i]+[int]$d[$i+1]*256+[int]$d[$i+2]*65536; if($v -band 0x800000){$v-=0x1000000}; $v }

$full=8388608.0; $sr=48000; $frame=6; $winFrames=[int]($sr*$WinMs/1000)
$rows=New-Object System.Collections.Generic.List[object]
foreach($pak in $Paks){
  $t=Get-PakEntries $pak
  $mic=Split-Path (Split-Path $pak -Parent) -Leaf
  $fs=[IO.File]::OpenRead($pak)
  try {
    foreach($e in $t.Entries){
      if($RrFilter -and $e.Name -notmatch $RrFilter){ continue }
      $fs.Position=$e.Off; $h=New-Object byte[] 128; $null=$fs.Read($h,0,128)
      $q=12;$dl=-1; while($q+8 -le 128){ $cid=[Text.Encoding]::ASCII.GetString($h,$q,4); $csz=[int][BitConverter]::ToUInt32($h,$q+4); if($cid -eq 'data'){$dl=$q+8;break}; $q=$q+8+$csz+($csz -band 1) }
      if($dl -lt 0){ continue }
      $need=[math]::Min($winFrames*$frame,[int]$e.Size-$dl)
      $fs.Position=$e.Off+$dl; $d=New-Object byte[] $need; $g=0; while($g -lt $need){ $r=$fs.Read($d,$g,$need-$g); if($r -le 0){break}; $g+=$r }
      $nf=[int]($g/$frame); if($nf -lt 1){ continue }
      $peak=0; $sumsq=0.0
      for($k=0;$k -lt $nf;$k++){ $i=$k*6; $l=S24l $d $i; $rr2=S24l $d ($i+3); $a=[math]::Max([math]::Abs($l),[math]::Abs($rr2)); if($a -gt $peak){$peak=$a}; $sumsq+=[double]$l*$l+[double]$rr2*$rr2 }
      $rms=[math]::Sqrt($sumsq/(2*$nf))
      $rows.Add([pscustomobject]@{ Mic=$mic; Note=($e.Name -split '_')[0];
        Vel=$(if($e.Name -match '_v(\d+)_'){[int]$matches[1]}else{0});
        RR=$(if($e.Name -match '_(rr\d+)'){$matches[1]}else{'rr1'});
        PeakDb=[math]::Round(20*[math]::Log10([math]::Max($peak,1)/$full),2);
        RmsDb=[math]::Round(20*[math]::Log10([math]::Max($rms,1)/$full),2) })
    }
  } finally { $fs.Close() }
  Write-Host "  $mic : total $($rows.Count)"
}
$rows | Export-Csv -NoTypeInformation $OutCsv
Write-Host "wrote $($rows.Count) rows -> $OutCsv"

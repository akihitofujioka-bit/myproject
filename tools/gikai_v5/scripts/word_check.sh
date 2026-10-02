#!/bin/zsh
# Mac の Word で .docx を開いて PDF に書き出し、ページごとの PNG にする（見た目の確認用）。
#   scripts/word_check.sh 試し出力/段階4_xxx.docx [倍率=1.6]
# PNG は $TMPDIR/word_check/<名前>_p<番号>.png に出る。
# osascript と Word の操作はサンドボックスの中では動かないので、Claude はこのコマンドだけサンドボックスを外して実行する。
set -e
here=${0:A:h}
docx=${1:A}
scale=${2:-1.6}
pdf=${docx:r}.pdf
out=${TMPDIR:-/tmp}/word_check
mkdir -p $out
rm -f $pdf
osascript <<OSA
tell application "Microsoft Word"
  open (POSIX file "$docx")
  delay 3
  set d to active document
  save as d file name "$pdf" file format format PDF
  close d saving no
end tell
OSA
bin=$out/pdf2png
[[ -x $bin ]] || swiftc -O $here/pdf2png.swift -o $bin -module-cache-path $out/mc
$bin $pdf $out/${docx:t:r} $scale
ls $out/${docx:t:r}_p*.png

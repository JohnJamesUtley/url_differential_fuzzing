echo Running both parsers!

echo
path1=$(python compare.py 0)
echo $path1
echo
python $path1 < $1

echo
path2=$(python compare.py 1)
echo $path2
echo
python $path2 < $1

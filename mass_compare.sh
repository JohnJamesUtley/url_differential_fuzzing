for FILE in $1*; do
    echo
    echo $FILE
    echo
    bash compare.sh $FILE
done

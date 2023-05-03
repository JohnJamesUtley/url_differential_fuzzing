for FILE in $1*; do
    echo
    echo $(cat $FILE)
    echo
    bash compare.sh $FILE
done

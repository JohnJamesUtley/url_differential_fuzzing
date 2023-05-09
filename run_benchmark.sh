for d in benchmarking/*/
do
cat ${d}/config.py > config.py
python diff_fuzz.py &> ${d}/run_out.txt
done
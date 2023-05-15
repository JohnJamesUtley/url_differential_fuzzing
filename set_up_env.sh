# This script should be sourced, not executed.

# Where the python packages are
PYTHON_PKG_DIR="./python_pkgs"
PYTHON_EXE="python3"

fail() {
    echo -en '\033[31mError: '
    echo $@
    echo "Installation has failed."
    echo -en '\033[0m'
    exit 1
}

# If there's a file in cpython/python, use that as our python binary instead
# (useful because as we've gotten fixes into cpython, and we don't want to keep
#  finding the same old bugs)
if [ -f "./cpython/python" ]; then
    echo "Using local (not system) python installation."
    PYTHON_EXE="$(pwd)/cpython/python"
fi

# Check for dependencies.
which afl-showmap &>/dev/null || fail "Please install AFL or AFL++."
which $PYTHON_EXE &>/dev/null || fail "Please install python3."
[ -n "$(ls $PYTHON_PKG_DIR/python-afl)" ] || fail "Looks like you're missing python-afl. Did you forget to clone this repository with \`--recurse-submodules\`?"

$PYTHON_EXE -c 'import sys; exit(sys.prefix != sys.base_prefix)' || fail "Looks like you're already in a venv. This script needs to make its own venv. Please deactivate your venv and source this script again."

rm -rf url_fuzz_env || fail "Couldn't remove old venv."
$PYTHON_EXE -m venv url_fuzz_env || fail "Couldn't make a venv."
source ./url_fuzz_env/bin/activate || fail "Couldn't activate the venv."
pip3 install --upgrade pip || { deactivate; fail "Couldn't update pip."; }

# These are the packages that we made submodules.
for PKG in $PYTHON_PKG_DIR/*; do
    YARL_NO_EXTENSIONS=1 pip3 install "$PKG" || { deactivate; fail "Couldn't install $PKG."; }
    # kind of a hack for yarl, but whatever
done

# These are the packages that we can just get from pypi
for PKG in hypothesis tqdm; do
    pip3 install "$PKG" || { deactivate; fail "Couldn't install $PKG."; }
done

# Get Ruby Afl
git clone https://github.com/richo/afl-ruby
cd afl-ruby/lib/afl
ruby ../../ext/afl_ext/extconf.rb
make
cd ../../../..

echo -e "\033[32mYou are now in the fuzzing venv. run \`deactivate\` to exit the venv.\033[0m"

import logging
import subprocess
from collections.abc import Iterable
from pathlib import Path
from shutil import rmtree

OUTPUT_DIRECTORY = Path.cwd() / 'rtl'
OUTPUT_DIRECTORY.mkdir(exist_ok=True)

GITHUB_REPOSITORIES = 'repos.txt'

logging.basicConfig(level=logging.DEBUG,
                    format='%(asctime)s %(name)-12s %(levelname)-8s %(message)s',
                    datefmt='%m-%d %H:%M',
                    filename='collector.log',
                    filemode='w')


def join_filepaths(filepaths: Iterable[str]):
    return " ".join(f'"{f}"' for f in filepaths)


def is_synthesizable(filepaths: Iterable[str]) -> str | None:
    """If the files are synthesizable, return the name of top module.
    Otherwise, return None."""

    def err_msg(reason: str) -> str:
        filelist = '\n\t'.join(filepaths)
        return f'{reason}:\n\t{filelist}\n'

    cmdline = ['yosys', '-qq', '-p', f'plugin -i systemverilog; read_systemverilog -synth {join_filepaths(filepaths)}']
    try:
        for line in subprocess.check_output(cmdline, timeout=1000).decode('utf-8').splitlines():
            if line.startswith('[NTE:EL0503]'):
                assert (start := line.find('@')) != -1
                assert (end := line[start + 1:].find('"')) != -1
                return line[start + 1:start + 1 + end]

    except Exception as err:
        reason = 'Unknown'
        if isinstance(err, subprocess.CalledProcessError):
            reason = 'Yosys exited unexpectedly'
        elif isinstance(err, subprocess.TimeoutExpired):
            reason = 'TIMEOUT'
        elif isinstance(err, AssertionError):
            reason = 'Top module not found'

        logging.fatal(err_msg(reason))
        return None


def archive(components: Iterable[str], filename: str) -> None:
    """Merge multiple files into a standalone file."""

    output_path = OUTPUT_DIRECTORY / filename
    cmdline = f'''cat {join_filepaths(components)} | sed '/^`/d' > {output_path.as_posix()}'''
    try:
        subprocess.run(cmdline, shell=True, check=True)
    except subprocess.CalledProcessError:
        filelist = '\n\t'.join(components)
        logging.fatal(f'Failed to merge files\n\t{filelist}\n')


def analyze(parent_dir: Path) -> None:
    """Analyze all .sv files under the parent_dir."""

    logging.info(f'\n\nStart analyzing [ {parent_dir.stem} ].')

    # Find all source files
    candidates = parent_dir.glob('**/*.sv')
    extracted = 0

    # Try to find the minimal compilable set for each .sv file
    for candidate in candidates:
        assert candidate.is_absolute()

        current_try = [candidate.as_posix()]

        if (top_module := is_synthesizable(current_try)):
            archive(current_try, f'{top_module}.sv')
            extracted += 1
        else:
            # For now, just give up
            logging.info(f'Drop "{candidate.as_posix()}"')

    total = int(subprocess.check_output(f'ls {parent_dir.as_posix()}/**/*.sv | wc -l', shell=True).decode('utf-8'))
    logging.info(f'Extracted {extracted} standalone modules out of {total} files.')


def clone_repo(repo_name: str, parent_dir: Path | None = None) -> Path:
    """Clone the repo under parent_dir (default=`Path.cwd()`).
    Return the path to the cloned directory."""

    def clone_url_of(repo_name: str) -> str:
        """Construct the web URL of given repository for cloning."""
        return f'https://github.com/{repo_name}.git'

    def shorter_name_of(repo_name: str) -> str:
        """The second part of a repo's name."""
        return repo_name[repo_name.find('/') + 1:]

    if not parent_dir:
        parent_dir = Path.cwd()

    subdir_name = shorter_name_of(repo_name)
    subprocess.run(f'cd {parent_dir.as_posix()} && git clone {clone_url_of(repo_name)} {subdir_name}', shell=True)

    return parent_dir / subdir_name


if __name__ == '__main__':
    repo_names = filter(lambda n: len(n) > 0, (n.strip() for n in open(GITHUB_REPOSITORIES, 'r')))
    for repo_name in repo_names:
        repo_path = clone_repo(repo_name)
        analyze(repo_path)
        rmtree(repo_path)

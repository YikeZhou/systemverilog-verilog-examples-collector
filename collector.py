import logging
import os
import re
import subprocess
from pathlib import Path
from random import choices
from shutil import rmtree
from string import ascii_letters

from tqdm import tqdm

OUTPUT_DIRECTORY = Path.cwd() / 'rtl'
OUTPUT_DIRECTORY.mkdir(exist_ok=True)

GITHUB_REPOSITORIES = 'repos.txt'

AUTO_TOP_MODULE = re.compile(r'Automatically selected (?P<top>[a-zA-Z_][a-zA-Z0-9_\$]*) as design top module.')
INCLUDE_DIRECTIVE = re.compile(r'`include\s+"(?P<filename>[\w\.\/]+)"')

logging.basicConfig(level=logging.DEBUG,
                    format='%(asctime)s %(name)-12s %(levelname)-8s %(message)s',
                    datefmt='%m-%d %H:%M',
                    filename='collector.log',
                    filemode='w')


def is_synthesizable(filepath: Path) -> str | None:
    """If the files are synthesizable, return the name of top module.
    Otherwise, return None."""

    cmdline = [os.environ['YOSYS_BINARY'], '-p']
    if filepath.suffix == '.sv':
        cmdline.append(f'plugin -i systemverilog; read_systemverilog -synth {filepath.as_posix()}')
    elif filepath.suffix == '.v':
        cmdline.append(f'read_verilog {filepath.as_posix()}; synth')
    else:
        logging.error(f'unsupported file extension "{filepath.suffix}"')
        return None

    try:
        output = subprocess.check_output(cmdline, timeout=1000).decode('utf-8')
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return None

    try:
        for line in output.splitlines():
            if line.startswith('[NTE:EL0503]'):
                assert (start := line.find('@')) != -1
                assert (end := line[start + 1:].find('"')) != -1
                return line[start + 1:start + 1 + end]
            if m := AUTO_TOP_MODULE.match(line):
                return m.group('top')

    except AssertionError:
        logging.debug(f'Top module not found:\n\t{filepath.as_posix()}\n')
        return None


def archive(component: Path, filename: str) -> Path:
    """Merge multiple files into a standalone file."""

    def random_prefix(length: int = 5) -> str:
        return ''.join(choices(ascii_letters, k=length)) + '_'

    output_path = OUTPUT_DIRECTORY / filename
    # Rename if this file already exists
    while output_path.exists():
        output_path = OUTPUT_DIRECTORY / (random_prefix() + filename)

    def replace_include(match: re.Match):
        """Replace the compiler directive [ `include "filename" ] with the entire contents."""

        try:
            n = match.group('filename')
            return (component.parent / n).read_text()
        except:
            # NOTE: The regex matching cannot exclude `include in comments or `ifdef blocks.
            # Therefore, it's necessary to handle `FileNotFoundError`s here.
            return ''  # Remove this line

    output_path.write_text(INCLUDE_DIRECTIVE.sub(replace_include, component.read_text()))
    return output_path


def analyze(parent_dir: Path) -> tuple[int, int]:
    """Analyze all .[sv|v] files under the parent_dir."""

    extracted = total = 0
    logging.info(f'\n\nStart analyzing [ {parent_dir.stem} ].')

    for file_extension in ('.sv', '.v'):

        # Find all source files
        candidates = list(parent_dir.glob(f'**/*{file_extension}'))
        total += len(candidates)

        for candidate in tqdm(candidates, desc=f'{parent_dir.stem}({file_extension})', total=len(candidates)):
            if (top_module := is_synthesizable(candidate)):
                filename = f'{top_module}{file_extension}'
                output_path = archive(candidate, filename)
                # Validate the output
                if is_synthesizable(output_path):
                    extracted += 1
                else:
                    logging.error(f'Failed to replace the `include directive in {candidate.as_posix()}')
                    output_path.unlink()

            else:
                # For now, just give up
                logging.debug(f'Drop "{candidate.as_posix()}"')

        logging.info(f'Extracted {extracted} standalone {file_extension} modules out of {total} files.')

    return (extracted, total)


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
    numerator = 0
    denominator = 0

    repo_names = filter(lambda n: len(n) > 0, (n.strip() for n in open(GITHUB_REPOSITORIES, 'r')))
    for repo_name in repo_names:
        repo_path = clone_repo(repo_name)
        extracted, total = analyze(repo_path)
        numerator += extracted
        denominator += total
        rmtree(repo_path)

    logging.info(f'Summary: {numerator}/{denominator}')

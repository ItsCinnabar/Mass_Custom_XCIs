from pathlib import Path
import pickle
import re
import subprocess

py_command = 'python'


def get_global_paths():
    global nsps, base, updates, dlc, output
    changed = False

    try:
        with open('path.pickle', 'r+b') as file:
            nsps = pickle.load(file)
            output = pickle.load(file)
    except (FileNotFoundError, AttributeError):
        nsps = Path(input('Enter NSPs Directory: '))
        output = input('Enter Output Directory: ')
        #  Squirrel -o cannot handle a trailing slash
        #  pathlib does not handle trailing slash from an input, but will handle it if passed later.
        output = Path(output)
        changed = True

    while True:
        base = nsps / 'base'
        updates = nsps / 'updates'
        dlc = nsps / 'dlc'
        if not base.exists() or not dlc.exists():
            changed = True
            print('Could not locate subdirectories.')
            print(f'Tried paths were:\n{base}\n{updates}\n{dlc}')
            nsps = Path(input('Enter nsps Directory: '))
        if not updates.exists() and base.exists() and dlc.exists():
            updates = nsps / 'updates (1)'
            if not updates.exists():
                print(f'base and dlc sub-folders found, updates sub-folder not found, '
                      f'nor was hbg meme of updates (1) sub-folder')
                nsps = Path(input('Enter nsps Directory: '))
        if base.exists() and dlc.exists() and updates.exists():
            break

    if changed:
        with open('path.pickle', 'wb') as file:
            pickle.dump(nsps, file)
            pickle.dump(output, file)
    return


def create_database():
    database = {}

    for file in base.glob('*.nsp'):
        title_id = re.findall(r'\[0100[a-zA-Z0-9]{12}]', str(file))
        if len(title_id) == 0:
            print(f'Error on {file}\n'
                  f'No title id found, ignoring base file.')
        elif len(title_id) > 1:
            print(f'Error on {file}\n'
                  f'{title_id[0]} and {title_id[1]} found\n'
                  f'Unable to determine correct title id, ignoring base file')
        else:
            database.update({title_id[0][1:-5]: [file]})

    for file in updates.glob('*.nsp'):
        title_id = re.findall(r'\[0100[a-zA-Z0-9]{12}]', str(file))
        if len(title_id) == 1 and title_id[0][1:-5] in database:
            database[title_id[0][1:-5]].append(file)

    for file in dlc.glob('*.nsp'):
        title_id = re.findall(r'\[0100[a-zA-Z0-9]{12}]', str(file))
        if len(title_id) == 1 and title_id[0][1:-5] in database:
            database[title_id[0][1:-5]].append(file)
    return database


def load_database():
    skip = 0
    old_database = {}
    try:
        with open('database.pickle', 'rb') as db:
            old_database = pickle.load(db)
    except (FileNotFoundError, EOFError):
        print('No database found')
        while True:
            skip = input('Enter 0 to start from scratch and create all XCIs\n'
                         'Enter 1 to create a complete database and no XCIs\n\n'
                         'Input : ')
            if skip not in ['0', '1']:
                print(f'{skip} is not an accepted answer')
            else:
                break

    return old_database, skip


def save_database(title_id, paths, old_database):
    with open('database.pickle', 'wb') as db:
        old_database[title_id] = paths
        pickle.dump(old_database, db)


def create_xci(title_id, paths):
    string = ''
    for path in paths:
        string += path.as_posix() + '\n'
    with open('multi.txt', 'w+', encoding='utf-8') as multi:
        multi.write(string)

    number_of_updates = number_of_dlc = name = 0
    for path in paths:
        if path.parent == base:
            name = path.stem
        if path.parent == updates:
            number_of_updates += 1
            name = path.stem
        if path.parent == dlc:
            number_of_dlc += 1

    if number_of_updates > 0 or number_of_dlc > 0:
        name += f' (1G'
        if number_of_updates > 0:
            name += f'+{number_of_updates}U'
        if number_of_dlc > 0:
            name += f'+{number_of_dlc}D'
        name += ')'

    root = Path.cwd()
    squirrel = subprocess.Popen(f'{py_command} "{root / "ztools/squirrel.py"}" '
                                f'-o "{output}" '
                                f'-dmul "file" '
                                f'-tfile "{root / "multi.txt"}" '
                                f'-t xci',
                                shell=True, stdout=subprocess.PIPE).stdout.read()
    nscb_xci = output / f'file[nscb].xci'

    if b"Exception" in squirrel:
        nscb_xci.unlink()
        print(f'Failed to create xci for {title_id}')
        print('The following is the output from NSCB as to why it failed:')
        print(squirrel)
        passed = False
    else:
        custom_xci = output / f'{name}.xci'
        try:
            nscb_xci.replace(custom_xci)
            print(f'Created {custom_xci}')
            print(f'This has the following files in it:\n{string}')
            passed = True
        except FileNotFoundError:
            print(f'Failed to create xci for {title_id}')
            print('PATHs messed up?')
            print('Python command not found?')
            print('Most likely not a NSCB failure, but its output below anyways')
            print(squirrel)
            passed = False

    return passed


def delete_old_xci(title_id):
    for file in output.glob('*.xci'):
        if re.search(r'\[' + title_id + '[a-zA-Z0-9]{4}]', str(file)):
            print(f'Deleted old file : {file}')
            file.unlink()
            break


def main():
    get_global_paths()
    old_database, skip = load_database()
    database = create_database()
    if skip == '1':
        with open('database.pickle', 'wb') as db:
            pickle.dump(database, db)
    else:
        for title_id, paths in database.items():
            if paths != old_database.get(title_id):
                delete_old_xci(title_id)
                passed = create_xci(title_id, paths)
                if passed:
                    save_database(title_id, paths, old_database)
    print('Done')


main()

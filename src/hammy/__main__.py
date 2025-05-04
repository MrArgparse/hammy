from datetime import datetime
from pathlib import Path, PurePosixPath
from PIL import Image
from rich.console import Console, Group
from rich.live import Live
from rich.logging import RichHandler
from rich.progress import Progress, BarColumn, MofNCompleteColumn, TextColumn
from requests.adapters import HTTPAdapter
from typing import Type
from urllib3.util.retry import Retry
from urllib.parse import urlparse, urlunparse
import argparse
import logging
import msgspec
import os
import requests
import platformdirs
import pyperclip
import sys
import tomlkit

EXTENSIONS = ['.bmp', '.gif', '.jpg', '.jpeg', '.png', '.webp']
PLATFORMDIRS = platformdirs.PlatformDirs(appname='hammy', appauthor=False)
CONFIG_FOLDER = PLATFORMDIRS.user_config_path
DEFAULT_CONFIGURATION_PATH = CONFIG_FOLDER / 'hammy_config.toml'
DEFAULT_ENCODING = 'utf-8'
logging.basicConfig(level=logging.INFO, format='%(message)s', datefmt='[%X]', handlers=[RichHandler()])

class DefaultConfig(msgspec.Struct):
	api_key: str = ''
	download_path: Path = CONFIG_FOLDER / 'downloads'
	resize_path: Path = CONFIG_FOLDER / 'resize'
	txt_path: Path = CONFIG_FOLDER / 'txt'

def parse_fappy() -> argparse.ArgumentParser:
	parser = argparse.ArgumentParser(prog='hammy')
	parser.add_argument('source', nargs='+', help='File, folder or url (recursive)')
	parser.add_argument('--clip', '-c', action='store_true', help='Sets the resulting links in the clipboard')
	parser.add_argument('--single', '-s', action='store_true', help='Outputs the links on a single line')
	parser.add_argument('--width', '-w', type=int, default=None, help='Resize images to desired width value in pixels')
	parser.add_argument('--format', default='d', choices=['b', 'd', 'h', 'i', 'm', 't', 'u'], help='Selects desired link formats')
	parser.add_argument('--txt', '-t', action='store_true', default=False, help='Outputs links to a text file')

	return parser

def encode_hook(obj: Path | str) -> str:

	if isinstance(obj, Path):

		return str(obj)

	return obj  

def decode_hook(type_: Type[Path], value: Path | str) -> Path | str:

	if type_ is Path and isinstance(value, str):

		return Path(value)

	return value

def get_config_path(path: Path | None = None) -> Path:

	if path is None:
		
		return DEFAULT_CONFIGURATION_PATH

	return Path(path).resolve()

def load_config(path: Path | None = None) -> DefaultConfig:
	path = get_config_path(path)

	with open(path, 'r', encoding=DEFAULT_ENCODING) as fp:
		data = fp.read()

	return msgspec.toml.decode(data, type=DefaultConfig, dec_hook=decode_hook)

def save_config(configuration: DefaultConfig, path: Path | None = None) -> None:
	path = get_config_path(path)
	data = tomlkit.dumps(msgspec.to_builtins(configuration, enc_hook=encode_hook))
	path.parent.mkdir(parents=True, exist_ok=True)

	with open(path, 'w', encoding=DEFAULT_ENCODING) as fp:
		fp.write(data)

	logging.info(f'New default config saved in: {DEFAULT_CONFIGURATION_PATH}')

def load_or_create_config(path: Path | None = None) -> DefaultConfig:
	path = get_config_path(path)

	if path.exists():
		logging.info(f'Previous config found in: {DEFAULT_CONFIGURATION_PATH}')

	try:

		return load_config(path)

	except FileNotFoundError:

		pass

	configuration = DefaultConfig()
	save_config(configuration, path)
	
	return configuration

CONFIG = load_or_create_config()

def create_retry() -> requests.Session:
	retry_strategy = Retry(total=2, status_forcelist=[429, 500, 502, 503, 504], allowed_methods=['HEAD', 'GET', 'OPTIONS'])
	adapter = HTTPAdapter(max_retries = retry_strategy)
	http = requests.Session()
	http.mount('https://', adapter)

	return http

def find_images(arg: Path) -> list[Path]:
	image_files = []

	for root, dirs, filenames in os.walk(arg):
 
		for filename in filenames:
			full_path = Path(root) / filename
 
			if full_path.suffix.lower() in EXTENSIONS:
				image_files.append(full_path)

	return sorted(image_files)

def organize_pics(filenames: list[Path]) -> list[Path]:
	pics = []

	for arg in filenames:

		if arg.is_dir():
			pics.extend(find_images(arg))

		if arg.is_file() and arg.suffix.lower() in EXTENSIONS:
			pics.append(arg)

	for index, pic in enumerate(pics):

		while pics[index].stat().st_size > 7600000:
			pics[index] = resize_pics(pics[index])

			if pics[index].stat().st_size >= 7600000:

				continue

	pics.sort()

	return pics

def resize_pics(pic: Path, resize_path: Path = CONFIG.resize_path) -> Path:
	img: Image.Image = Image.open(pic)
	img_size = pic.stat().st_size
	width, height = img.size
	new_width = 0

	while new_width < 300:

		try:
			new_width = int(input(f'Image size is too big! Current Size: {img_size}{os.linesep}Current width: {width}{os.linesep}Enter new width: '))

			if new_width < 300:

				raise ValueError

		except ValueError:
			logging.error('Invalid input. Please enter a valid integer greater than 300.')

	new_height = round(new_width * height / width)
	img = img.resize((new_width, new_height), Image.Resampling.LANCZOS)
	resize_path.mkdir(parents=True, exist_ok=True)
	fname = resize_path / pic.name
	img.save(fname)

	return fname

def download_image(url: str) -> Path:
	r = requests.get(url)
	CONFIG.download_path.mkdir(parents=True, exist_ok=True)
	file_name = PurePosixPath(url).name
	dl_path = CONFIG.download_path / file_name

	with open(dl_path, 'wb') as f:
		f.write(r.content)
	
	return dl_path

def upload_image(image_path: Path, width: int | None = None) -> tuple[str, str]:
	url = 'https://hamster.is/api/1/upload'
	headers = {'X-API-Key': CONFIG.api_key}
	http = create_retry()

	if width:
		headers['width'] = str(width)

	fspath = str(image_path)

	with open(fspath, 'rb') as f:
		file = {'source': (fspath, f, 'application/octet-stream')}
		response = http.post(url, headers=headers, files=file)

	if not response.ok:
		error_dict: dict[str, int | str] = response.json()['error']
		error_dict['file'] = image_path.name
		logging.error(error_dict)
		response.raise_for_status()

	link = response.json()['image']['url']
	image_id = response.json()['image']['id_encoded']
	
	return link, image_id

def get_progress(process_type: str) -> tuple[Progress, Progress]:
	description_progress =  Progress(TextColumn(f'{process_type} ' + 'file: {task.fields[extra]}'), auto_refresh=False)
	progress_bar = Progress(TextColumn('[progress.percentage]{task.percentage:>3.0f}%'), BarColumn(), MofNCompleteColumn(), auto_refresh=False)

	return description_progress, progress_bar

def save_txt(path_name: Path, text_string: str) -> None:
	path_name.parent.mkdir(parents=True, exist_ok=True)

	with open(path_name, 'a', encoding='utf-8', newline='\n') as txt_file:
		txt_file.write(text_string)

def get_out(out: Path) -> Path:
	date: str = datetime.today().strftime('%Y-%m-%d-%H-%M-%S')
	path_name = out / f'links-{date}.txt'

	return path_name

def format_links(link_format: list[str], link: str, image_id: str) -> str:
	result = ''

	match link_format:

		case 'b':
			result = f'[img]{link}[/img]'

		case 'd':
			result = link

		case 'h':
			result = f'[url=https://hamster.is/image/{image_id}][img]{change_url_suffix(link, 'th')}[/img][/url]'

		case 'i':
			result = f'[imgnm]{link}[/imgnm]'

		case 'm':
			result = f'{change_url_suffix(link, '.md')}'

		case 't':
			result = f'{change_url_suffix(link, '.th')}'
		
		case 'h':
			result = f'[url=https://hamster.is/image/{image_id}][img]{change_url_suffix(link, 'md')}[/img][/url]'

	return result

def change_url_suffix(url: str, new_suffix: str) -> str:
	parts = urlparse(url)
	path = PurePosixPath(parts.path)
	new_path = path.with_suffix(f'{new_suffix}{path.suffix}')
	new_parts = parts._replace(path=str(new_path))

	return urlunparse(new_parts)

def is_url(s: str) -> bool:
	parsed = urlparse(s)

	return parsed.scheme in ("http", "https") and bool(parsed.netloc)

def separate_sources(sources: list[str]) -> tuple[list[str], list[Path]]:
	urls = [s for s in sources if is_url(s)]
	files_or_dirs = [Path(s) for s in sources if not is_url(s)]

	return urls, files_or_dirs

def main() -> None:
	parser = parse_fappy()
	args = parser.parse_args(sys.argv[1:])
	urls, files_or_dirs = separate_sources(args.source)

	if files_or_dirs:
		pics = organize_pics(files_or_dirs)

	if urls:
		downloads = []
		total = len(urls)

		if sys.stdout.isatty():
			description_progress0, progress_bar0 = get_progress('Downloading')
			group0 = Group(description_progress0, progress_bar0)

		else:
			group0 = None

		with Live(group0):

			if group0:
				task0= progress_bar0.add_task('Task 0', total=total)
				task1 = description_progress0.add_task('Task 1', total=total, extra=urls[0])

			for u in urls:
			
				try:
					dl = download_image(u)

				except (ValueError, requests.exceptions.HTTPError) as e:
					logging.error(f'{type(e).__name__}: {e}')

					continue

				downloads.append(dl)

				if group0:
					progress_bar0.update(task0, advance=1, refresh=True)
					description_progress0.update(task1, advance=1, refresh=True, extra=u)

		pics.extend(downloads)

	if not pics:
		logging.error(f'No compatible arguments.')
		sys.exit(1)

	total = len(pics)
	fname = Path(pics[0]).name
	result_string = []

	if sys.stdout.isatty():
		description_progress1, progress_bar1 = get_progress('Uploading')
		group1 = Group(description_progress1, progress_bar1)

	else:
		group1 = None

	with Live(group1):

		if group1:
			task3 = progress_bar1.add_task('Task 3', total=total)
			task4 = description_progress1.add_task('Task 4', total=total, extra=fname)

		for pic in pics:
			fname = pic.name
			width = args.width if args.width else None

			try:
				link, image_id = upload_image(pic, width)

			except (AttributeError, KeyError, requests.exceptions.HTTPError, ValueError) as e:
				logging.error(f'{type(e).__name__}: {e}')

				continue

			result_string.append(format_links(args.format, link, image_id))

			if group1:
				progress_bar1.update(task3, advance=1, refresh=True)
				description_progress1.update(task4, advance=1, refresh=True, extra=fname)

	if args.single:
		text_string = ''.join(result_string)

	else:
		text_string = '\n'.join(result_string)

	if args.clip:
		pyperclip.copy(text_string)

	if args.txt:
		txt_path = CONFIG.txt_path
		path_name = get_out(txt_path)
		save_txt(path_name, text_string)

	Console().print(text_string, markup=False)

if __name__  ==  '__main__':
	main()

from datetime import datetime
from json import JSONDecodeError
from fake_useragent import UserAgent
from pathlib import Path, PurePosixPath
from PIL import Image
from rich.console import Console
from rich.logging import RichHandler
from requests.adapters import HTTPAdapter
from typing import Type, BinaryIO
from urllib3.util.retry import Retry
from urllib.parse import urlparse, urlunparse
import argparse
import logging
import msgspec
import imagequant
import io
import os
import random
import requests
import platformdirs
import pyperclip
import shutil
import sys
import tomlkit

EXTENSIONS = frozenset(['.bmp', '.gif', '.jpg', '.jpeg', '.png', '.webp'])
PLATFORMDIRS = platformdirs.PlatformDirs(appname='hammy', appauthor=False)
CONFIG_FOLDER = PLATFORMDIRS.user_config_path
DEFAULT_CONFIGURATION_PATH = CONFIG_FOLDER / 'hammy_config.toml'
DEFAULT_ENCODING = 'utf-8'
logging.basicConfig(
    level=logging.INFO, format='%(message)s', datefmt='[%X]', handlers=[RichHandler()]
)


class DefaultConfig(msgspec.Struct, kw_only=True):
    api_key: str = ''
    txt_path: Path = CONFIG_FOLDER / 'txt'


def parse_hammy() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog='hammy')
    parser.add_argument('source', nargs='+', help='File, folder or url (recursive)')
    parser.add_argument(
        '--clip',
        '-c',
        action='store_true',
        help='Sets the resulting links in the clipboard',
    )
    parser.add_argument(
        '--single', '-s', action='store_true', help='Outputs the links on a single line'
    )
    parser.add_argument(
        '--width',
        '-w',
        type=int,
        default=None,
        help='Resize images to desired width value in pixels',
    )
    parser.add_argument(
        '--format',
        default='d',
        choices=['b', 'd', 'h', 'i', 'm', 't', 'u'],
        help='Selects desired link formats',
    )
    parser.add_argument(
        '--txt',
        '-t',
        action='store_true',
        default=False,
        help='Outputs links to a text file',
    )
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

if not CONFIG.api_key:
    try:
        CONFIG.api_key = input('Enter api key: ')

        if CONFIG.api_key:
            save_config(CONFIG)
        else:
            raise ValueError('Input field was empty')

    except ValueError as e:
        logging.error(f'{type(e).__name__}: {e}')
        logging.shutdown()
        sys.exit(1)


def get_useragent_header() -> dict[str, str]:
    ua = UserAgent()
    return {'User-Agent': ua.chrome}


USER_AGENT_HEADER = get_useragent_header()


def ensure_directories_exist(config: DefaultConfig) -> None:
    for field in config.__struct_fields__:
        value = getattr(config, field)

        if isinstance(value, Path):
            if not value.suffix:
                value.mkdir(parents=True, exist_ok=True)


ensure_directories_exist(CONFIG)


def create_retry() -> requests.Session:
    retry_strategy = Retry(
        total=2,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=['HEAD', 'GET', 'OPTIONS'],
    )
    adapter = HTTPAdapter(max_retries=retry_strategy)
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


def organize_pics(filenames: list[Path | str]) -> list[Path | str]:
    pics: list[Path | str] = []

    for arg in filenames:
        if isinstance(arg, Path) and arg.is_dir():
            pics.extend(find_images(arg))
        else:
            ext = os.path.splitext((arg))[1]

            if ext in EXTENSIONS:
                pics.append(arg)

    pics.sort()
    return pics


def check_width(new_width: int, width: int) -> int:
    try:
        new_width = int(input(f'Current width: {width}{os.linesep}Enter new width: '))

        if new_width < 1 or new_width >= width:
            raise ValueError
 
    except ValueError:
        logging.error(
            'Invalid input. Enter a valid integer greater than 0 and lower than the current width.'
        )

    return new_width


def is_animated(img_bytes: BinaryIO) -> bool:
    with Image.open(img_bytes) as img:
        return getattr(img, "n_frames", 1) > 1

    
def get_new_dimensions(width: int, height: int, resize: int | None) -> tuple[int, int]:
    new_width = 0

    if resize is not None:
        new_width = resize

    while new_width < 1 or new_width >= width:
        new_width = check_width(new_width, width)

    new_height = round(new_width * height / width)
    return new_width, new_height


def resize_pics(
    img_bytes: BinaryIO, resize_output: BinaryIO, resize: int | None = None
) -> BinaryIO:
    with Image.open(img_bytes) as img:
        width, height = img.size
        new_width, new_height = get_new_dimensions(width, height, resize)
        img = img.resize((new_width, new_height), Image.Resampling.LANCZOS)
        img.save(resize_output, format='JPEG')
        resize_output.seek(0)
        return resize_output


def resize_animations(
    img_bytes: BinaryIO, resize_output: BinaryIO, ext: str, resize: int | None = None
) -> BinaryIO:
    with Image.open(img_bytes) as img:
        width, height = img.size
        new_width, new_height = get_new_dimensions(width, height, resize)
        duration = img.info.get("duration", 100)
        loop = img.info.get("loop", 0)

        frames = []
        for frame in range(img.n_frames):
            img.seek(frame)
            original = img.copy()
            resized = original.resize((new_width, new_height), Image.Resampling.LANCZOS)
            quantized = imagequant.quantize_pil_image(
                resized,
                dithering_level=1.0,
                max_colors=256,
                min_quality=0,
                max_quality=80
            )
            frames.append(quantized)

        frames[0].save(
            resize_output,
            format=ext,
            save_all=True,
            append_images=frames[1:],
            loop=loop,
            duration=duration,
            disposal=2,
        )

        resize_output.seek(0)
        return resize_output


def download_image(url: str, output: BinaryIO) -> BinaryIO:
    r = requests.get(url, headers=USER_AGENT_HEADER)
    r.raise_for_status()
    output.write(r.content)
    output.seek(0)
    return output


def make_it_unique(input: BinaryIO, output: BinaryIO) -> BinaryIO:
    shutil.copyfileobj(input, output)
    output.write(random.randbytes(16))
    output.seek(0)
    return output


def get_byte_size(buffer: BinaryIO) -> int:
    return len(io.BytesIO(buffer.read()).getvalue())


def check_img_size(buffer: BinaryIO, ext: str) -> BinaryIO:
    while get_byte_size(buffer) > 7600000:
        logging.warning(
            f'Image size is too big! Current Size: {get_byte_size(buffer)}'
        )
        buffer = resize_animations(buffer, io.BytesIO(), ext) if is_animated(buffer) else resize_pics(buffer, io.BytesIO())

    buffer.seek(0)
    return buffer


def upload_image(image_path: Path | str, resize: int | None = None) -> tuple[str, str]:
    url = 'https://hamster.is/api/1/upload'
    headers = {'X-API-Key': CONFIG.api_key}
    http = create_retry()
    basename = os.path.basename(os.fspath(image_path))
    ext = os.path.splitext(image_path)[1][1:]
    str_path = os.fspath(image_path)

    if is_url(str_path):
        download = download_image(str_path, io.BytesIO())

        if resize:
            if is_animated(download):
                dl_buffer = resize_animations(download, io.BytesIO(), ext, resize)
            else:
                dl_buffer = resize_pics(download, io.BytesIO(), resize)
        else:
            dl_buffer = download

        unique = make_it_unique(dl_buffer, io.BytesIO())

    else:
        with open(image_path, 'rb') as buffer:

            if resize:
                if is_animated(buffer):
                    processed_buffer = resize_animations(buffer, io.BytesIO(), ext, resize)
                else:
                    processed_buffer = resize_pics(buffer, io.BytesIO(), resize)
            else:
                processed_buffer = buffer

            unique = make_it_unique(processed_buffer, io.BytesIO())

    final = check_img_size(unique, ext)
    file = {'source': (basename, final)}
    response = http.post(url, headers=headers, files=file)

    if not response.ok:
        try:
            error_json = response.json()
            error_dict = error_json.get('error', {'message': 'No error field in JSON'})
        except (ValueError, JSONDecodeError):
            error_dict = {'message': response.text.strip() or 'No error message'}

        error_dict['file'] = os.path.basename(image_path)
        logging.error(error_dict)
        response.raise_for_status()

    link = response.json()['image']['url']
    image_id = response.json()['image']['id_encoded']
    return link, image_id


def save_txt(path_name: Path, text_string: str) -> None:
    path_name.parent.mkdir(parents=True, exist_ok=True)

    with open(path_name, 'a', encoding='utf-8') as txt_file:
        txt_file.write(text_string)


def get_out() -> Path:
    date: str = datetime.today().strftime('%Y-%m-%d-%H-%M-%S')
    path_name = CONFIG.txt_path / f'links-{date}.txt'
    return path_name


def format_links(link_format: str, link: str, image_id: str) -> str:
    result = ''

    match link_format:
        case 'b':
            result = f'[img]{link}[/img]'

        case 'd':
            result = link

        case 'h':
            result = f'[url=https://hamster.is/image/{image_id}][img]{change_url_suffix(link, ".th")}[/img][/url]'

        case 'i':
            result = f'[imgnm]{link}[/imgnm]'

        case 'm':
            result = f'{change_url_suffix(link, ".md")}'

        case 't':
            result = f'{change_url_suffix(link, ".th")}'

        case 'u':
            result = f'[url=https://hamster.is/image/{image_id}][img]{change_url_suffix(link, ".md")}[/img][/url]'

    return result


def change_url_suffix(url: str, new_suffix: str) -> str:
    parts = urlparse(url)
    path = PurePosixPath(parts.path)
    new_path = path.with_suffix(f'{new_suffix}{path.suffix}')
    new_parts = parts._replace(path=str(new_path))
    return urlunparse(new_parts)


def is_url(s: str) -> bool:
    parsed = urlparse(s)
    return parsed.scheme in ('http', 'https') and bool(parsed.netloc)


def sort_sources(sources: list[str]) -> list[Path | str]:
    sorted_sources: list[Path | str] = []

    for s in sources:
        if is_url(s):
            sorted_sources.append(s)
        else:
            sorted_sources.append(Path(s))

    return sorted_sources


def main() -> None:
    parser = parse_hammy()
    args = parser.parse_args(sys.argv[1:])
    resize = args.width
    sorted_sources = sort_sources(args.source)
    pics = organize_pics(sorted_sources)

    if not pics:
        logging.error(f'No compatible arguments.')
        logging.shutdown()
        sys.exit(1)

    if args.clip:
        pyperclip.copy("")

    if args.txt:
        output_path = get_out()

    for idx, pic in enumerate(pics):
        final_link = ''

        try:
            link, image_id = upload_image(pic, resize)
        except (
            AttributeError,
            requests.exceptions.HTTPError,
        ) as e:
            logging.error(f'{type(e).__name__}: {e}')
            continue

        final_link = format_links(args.format, link, image_id)
        Console().print(final_link, markup=False)

        if idx < len(pics) - 1 and not args.single:
            final_link = final_link + '\n'

        if args.clip:
            pyperclip.copy(pyperclip.paste() + final_link)

        if args.txt:
            save_txt(output_path, final_link)

if __name__ == '__main__':
    main()
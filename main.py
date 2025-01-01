import logging
logging.basicConfig(level=logging.INFO, force=True)
logging.info("Warming up...")

import os, functools, pathlib, shutil, requests, sqlite3
from tqdm.auto import tqdm

from serve import Server
from zimply import ZIMFile
from search_index import Searcher

def create_index(zim_pth, index_pth):
    logging.warning("environment variable 'MESHWIKI_INDEXURL' is not set, will take a looooong while to create index from provided zim file")

    zim = ZIMFile(zim_pth, encoding="utf-8")
    num_articles = len(zim)
    db = sqlite3.connect(index_pth + "_tmp")
    db.execute("CREATE VIRTUAL TABLE articles USING fts4(content='', title, tokenize=porter);")

    for (idx, (url, title, index)) in enumerate(iter(zim)):  
        if url:
            title = url.replace("_", "")
            title = title.replace("(disambiguation)", "")
            db.execute("INSERT INTO articles(rowid, title) VALUES (?, ?)", (index, title))

        if idx % 10000 == 0:
            print(f"TEXT INDEXING {(idx/num_articles) * 100:.2f}%", end = "\r")
            db.commit()
    
    print()
    db.close()
    os.rename(index_pth + "_tmp", index_pth) # Prevent partial indexing (horrible way to do it)

def download(url, dst):
    if os.path.exists(dst):
        logging.info(f"'{dst}' exists, skipping download")
        return

    logging.info(f"'{dst}' does not exist! Downloading...")

    r = requests.get(url, stream=True, allow_redirects=True)
    if r.status_code != 200:
        r.raise_for_status()
        raise RuntimeError(f"Request to {url} returned status code {r.status_code}")
    
    file_size = int(r.headers.get('Content-Length', 0))
    path = pathlib.Path(dst + "_tmp").expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)

    desc = "(Unknown total file size)" if file_size == 0 else ""
    r.raw.read = functools.partial(r.raw.read, decode_content=True)
    with tqdm.wrapattr(r.raw, "read", total=file_size, desc=desc) as r_raw:
        with path.open("wb") as f:
            shutil.copyfileobj(r_raw, f)

    os.rename(dst + "_tmp", dst) # Prevent partial downloads

def download_wikipedia():
    zim_url = os.environ.get("MESHWIKI_ZIMURL", None)
    index_url = os.environ.get("MESHWIKI_INDEXURL", None)

    assert not zim_url is None, "environment variable 'MESHWIKI_ZIMURL' must be set"

    zim_pth = "zim_data/" + zim_url.split("/")[-1].split("?")[0]
    index_pth = zim_pth.replace(".zim", ".index")

    logging.info(f"Zim path: {zim_pth}")
    logging.info(f"Index path: {index_pth}")

    download(zim_url, zim_pth)
    if index_url is None and not os.path.exists(index_pth):
        create_index(zim_pth, index_pth)
    else:
        download(index_url, index_pth)

    return zim_pth, index_pth

if __name__ == "__main__":
    zim, index = download_wikipedia()
    Server(Searcher(zim, index)).start()
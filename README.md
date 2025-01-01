# MeshWiki
Offline wikipedia

<img src=sample.jpg width=300px>

## Commands

**/help** </br> Shows available commands

**/info** </br> Short text on what the project is about

**/search <query>** </br> Actually searches wikipedia and returns article *summary*

**/dump** </br> Used after /search to return the *entire* found article

## Building & Running

I recommend setting up a raspberry pi and connecting your meshtastic device via usb, then running the python command below. The script should automatically download the Simple English Wikipedia, build the index, and connect to the mesh. Should take ~10 minutes and about 1gb of storage.

### Environment Variables / Configuration

**MESHWIKI_ZIMURL** - Set to the url of the zim file you wish to index (must be wikipedia format!), see [dumps](https://dumps.wikimedia.org/kiwix/zim/wikipedia/) </br>
**MESHWIKI_REMOTE** - If the meshtastic device is on the same network, set as the host address OR</br>
**MESHWIKI_SERIAL** - If there are multiple meshtastic devices connected via usb, then set this variable to the target device, eg: /dev/ttyUSB0</br>

### Python

Make sure to install [python](https://www.python.org/downloads/), then run:
```
MESHWIKI_ZIMURL='https://dumps.wikimedia.org/kiwix/zim/wikipedia/wikipedia_en_simple_all_mini_2024-06.zim' python main.py
```

### Docker (not recommended for beginners)

Building:
```
sudo docker build -t meshwiki . --no-cache
```

Running:
```
sudo docker run --privileged -it --rm -e MESHWIKI_ZIMURL='https://dumps.wikimedia.org/kiwix/zim/wikipedia/wikipedia_en_simple_all_mini_2024-06.zim' meshwiki
```


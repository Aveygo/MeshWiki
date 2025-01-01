from search_index import Searcher, Article

import meshtastic.tcp_interface
import meshtastic.serial_interface
from meshtastic.stream_interface import StreamInterface
from meshtastic.protobuf.mesh_pb2 import DATA_PAYLOAD_LEN

from pubsub import pub
import time, os, logging


class Server:
    def __init__(self, searcher:Searcher):
        self.interface = self.load_interface()

        self.searcher = searcher
        self.dump_memory = {}

    def start(self):
        pub.subscribe(self.onReceive, 'meshtastic.receive')
        logging.info("Started")
        while True:
            time.sleep(10)

    def load_interface(self):
        remote_address = os.environ.get("MESHWIKI_REMOTE", None)
        serial_port = os.environ.get("MESHWIKI_SERIAL", None)
        
        if remote_address:
            return meshtastic.tcp_interface.TCPInterface(hostname=remote_address)    
        elif serial_port:
            return meshtastic.serial_interface.SerialInterface(devPath=serial_port)
        
        maybe_serial = meshtastic.serial_interface.SerialInterface()
        assert hasattr(maybe_serial, "stream"), "No serial ports with a meshtastic device detected..."
        return maybe_serial

    def send(self, message:str, to:str):
        flat = message.replace('\n', ' ')
        logging.info(f"Sending [{len(flat.encode('utf-8'))}/{DATA_PAYLOAD_LEN}]: {flat}")
        self.interface.sendText(message, to, wantAck=True)

    def handle_get(self, query:str, from_id:str) -> None:
        if query == "<query>":
            self.send("Please replace <query> with what you want to search for, eg:\n/get meshtastic", from_id)

        result:Article = self.searcher(query)
        if result is None:
            self.send(f"Nothing found for: '{query}'", from_id)
            return
        
        self.dump_memory[from_id] = {"content":result.summary, "confirmed":False, "query":query}
        result:str = result.summary.split(". ")[0]
        result_length = len(result.encode('utf-8'))

        logging.info(f"Found result with length {result_length} {'(too long)' if result_length > DATA_PAYLOAD_LEN else ''}")

        if result_length > DATA_PAYLOAD_LEN:
            self.send(f"Sorry, the found result was too long for meshtastic ({result_length} characters)", from_id)
            return
            
        self.send(result, from_id)

    def handle_dump(self, args:str, from_id:str) -> str:
        if not from_id in self.dump_memory:
            return f"Get an article using /get <query> before attempting a dump."

        content = self.dump_memory[from_id]["content"]
        query = self.dump_memory[from_id]["query"]
        confirmed = self.dump_memory[from_id]["confirmed"]

        max_length = 100 - 6
        total_length = len(content.encode("utf-8"))
        num_chunks = total_length // max_length

        if not confirmed:
            self.dump_memory[from_id]["confirmed"] = True
            est_time = int(len(content) / max_length * 5)  
            self.send(f"The full article for {query} will take ~{est_time} seconds to dump. If you want to continue, type /dump again.", from_id)
        else:
            for i in range(0, len(content.encode("utf-8")), max_length-1): 
                self.send(f"[{i//(max_length-1)}/{num_chunks}] " + content.encode("utf-8")[i:i + max_length-1].decode("utf-8"), from_id)
                time.sleep(5)
            
            del self.dump_memory[from_id]


    def handle_info(self, args:str, from_id:str) -> str:
        self.send(f"I am an offline search engine for Simple Wikipedia; originally created by Aveygo.\nArticles are {self.searcher.age} months old.", from_id)

    def handle_help(self, args:str, from_id:str) -> str:
        self.send("Available commands:\n/info\n/get <query>\n/dump", from_id)

    def handle_unknown(self, input_text:str, from_id:str) -> str:
        self.send(f"Type '/help' to get started!", from_id)

    def act(self, input_text:str, from_id=str) -> str:
        commands = {
            "/info": self.handle_info,
            "/get": self.handle_get,
            "/help": self.handle_help,
            "/dump": self.handle_dump
        }

        parts = input_text.split(maxsplit=1)
        cmd = parts[0]
        arg = parts[1] if len(parts) > 1 else None

        if cmd in commands:
            logging.info(f"Parsed command: {cmd}, arg: {arg}")
            commands[cmd](arg, from_id)
        else:
            logging.info(f"Could not parse: {input_text}")
            self.handle_unknown(input_text, from_id)
        

    def onReceive(self, packet, interface:StreamInterface):
        if 'decoded' in packet and packet['decoded']['portnum'] == 'TEXT_MESSAGE_APP':
            command:str = packet['decoded']['payload'].decode('utf-8')
            self.act(command, packet["fromId"])



if __name__ == "__main__":
    Server().start()
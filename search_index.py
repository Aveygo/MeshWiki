from model2vec import StaticModel
from zimply import ZIMFile, BM25

import sqlite3, numpy as np, time
from datetime import datetime
from pydantic import BaseModel

from markdownify import markdownify as md

EXTRA_ARTICLES = {
    "meshtastic": "**Meshtastic** is a decentralized protocol to send long range messages between devices while also using very little power. When a user wants to send a message to the network, they use a technique called LoRa to broadcast their message to their neighbors. Each neighbor then repeats this process until the maximum number of hops is achieved. Because each user is part of the \"mesh\", it does not require existing existing infrastructure such as cell towers, so it is very useful for emergency scenarios or in remote areas. Users can also setup encrypted channels for better privacy or security. To join Meshtastic, users will require a LoRa transmitter/receiver chip and a microprocessor to communicate with it, which is easily purchased as a commercially available board such as the HeltecV3."
}

class Candidate(BaseModel):
    row_id: int
    summary: str
    url: str
    emb_score: float
    bm25_score: float

class Article(BaseModel):
    summary: str
    query_duration: float


class Searcher:
    """
    
    Attempts to find query in zim file, example:
    
    ```
    search = Searcher()
    print(search("zombie")) # Returns either a None or an Article object 
    ```

    """
    def __init__(
            self, 
            zim_location:str, 
            index_location:str, 
            potion_location:str="minishlab/potion-base-8M"
        ):
        self.zim = ZIMFile(zim_location, encoding="utf-8")
        self.db = sqlite3.connect(index_location, check_same_thread=False)
        self.model = StaticModel.from_pretrained(potion_location)
        self.locked = False
        
        date = zim_location.split("_")[-1].split(".")[0].split("-")
        self.age = self._age_months(int(date[0]), int(date[1]))
    
    def _age_months(self, year, month):
        now = datetime.now()
        return (now.year - year) * 12 + (now.month - month)
    
    def _html_to_text(self, content:str) -> str | None:
        """
        Converts wikipedia html into a usable summary.
        It is assumed that the summary begins under the first header, which looks like:

        ```
        TITLE
        =====

        SUMMARY...
        ```
        """
    
        full_content = md(content, strip=['a'])
        title = full_content.split("\n")[2]
        summary = full_content.split("=\n")[1].split("\n")[1]

        # Zim is weird cause it may return a valid page, but it wants to go to wiktionary
        if "in Wiktionary, the free dictionary" in full_content:
            return None
        
        # Wikipedia portals. Contains lots of useful articles but no definitions
        if title.startswith("Portal:"):
            return None
        
        # Some articles are deleted
        if summary.endswith("debate+closed+as+delete"):
            return None

        # Default article
        if "**Article name here**" in summary:
            return f"'{title}' was created but unfortunately left empty"
        
        # Articles on broad topics
        # Please note that if the article lists the sub-topics in multiple headers, they
        # will be skipped. This is intended behavior as otherwise the summary will contain
        # too many links 
        if summary.endswith("may also refer to:") or summary.endswith("may refer to:"):
            holds_list = full_content.split("refer to:\n\n")[1]
            holds_list = holds_list.split("\n\n")[0].split("\n")
            summary += "\n" + "\n".join(holds_list)

        # Skip if sub-topics contained under other headers
        if summary.endswith("may also refer to:\n") or summary.endswith("may refer to:\n"):
            return None

        # Remote attribution if accidentally picked up
        summary = "\n".join(i for i in summary.split("\n") if not i.startswith("This article is issued from Wikipedia."))
        
        # Return result
        return summary

    def _get_fast_article(self, query:str) -> None | Article:
        """
        Fast zim index query: either finds direct match or fails.
        """
        a = time.time()
        maybe_fast_result = self.zim.get_article_by_url("A", query.title().replace(" ", "_"))
        if not maybe_fast_result is None:
            summary = self._html_to_text(maybe_fast_result.data)

            if summary is None:
                return None
            
            return Article(
                summary=summary, 
                query_duration=time.time() - a
            )
        
        return None
    
    def _compute_candidates(self, query:str) -> list[Candidate]:
        """
        Get all matches from full text matches from sqlite, then use 
        bm25 & embeddings to sort results.
        """
        results = self.db.execute("SELECT rowid FROM articles WHERE title MATCH ?", ["* ".join(query.split(" ")) + "*"]).fetchall()
        if len(results) == 0:
            return []
        
        if len(results) > 2000:
            # Return error message as a candidate
            return [
                Candidate(
                    row_id=-1, 
                    summary=f"Query had too many candidates to sort through: {len(results)}",
                    url="na",
                    emb_score=0,
                    bm25_score=0
                )
            ]
        
        if len(results) > 500:
            print(f"Large number of candidates found: {len(results)}")

        query_emb = self.model.encode(query)
        bm25 = BM25()
        candidates = []

        # Get the data necessary to sort each of the found articles
        for row in results:
            url = self.zim.read_directory_entry_by_index(row[0])["url"]

            # Mainly for embedding encoding
            cleaned_url = url.replace("_", "").replace("(disambiguation)", "").replace("(", "").replace(")", "")
            
            entry = self.zim._get_article_by_index(row[0])
            summary = self._html_to_text(entry.data)
            
            if not summary is None and len(summary):
                embeddings = self.model.encode(cleaned_url)
                candidates.append([row[0], summary, cleaned_url, np.dot(query_emb, embeddings)])
        
        if len(candidates) == 0:
            return []

        # Calculate BM25 scores for each candidate
        scores = bm25.calculate_scores(query.split(" "), [i[1] for i in candidates])

        # Convert to candidate objects for future sorting
        return [
            Candidate(
                row_id = i[0],
                summary = i[1],
                url = i[2],
                emb_score = i[3],
                bm25_score = i[4]
            )

            for i in [i + [scores[idx]] for idx, i in enumerate(candidates)]
        ]

    def _get_slow_article(self, query:str) -> None | Article:
        """
        Sorts all matches with query in the index. Much slower as it has to 
        compute scores (embeddings & BM25), up to a dozen seconds on a decent pc.
        """
        a = time.time()
        candidates = self._compute_candidates(query)
        candidates = sorted(candidates, key=lambda candidate: candidate.emb_score * candidate.bm25_score)
        if len(candidates):

            result = candidates[-1]
            return Article (
                summary=result.summary,
                query_duration=time.time() - a
            )

        return None

    def _get_extra_article(self, query:str) -> None | Article:
        if query in EXTRA_ARTICLES:
            return Article(
                summary=EXTRA_ARTICLES[query],
                query_duration=0
            )

        return None
    
    def _perform_search(self, query:str) -> None| Article:
        """
        Works in two stages:
            1. Fast, tries to find exact match in zim file without using the index
            2. Slow, uses the index and scoring functions
        
        If stage 1 fails, then stage 2 tries to find query.
        """
        maybe_fast_result = self._get_fast_article(query)
        if isinstance(maybe_fast_result, Article):
            return maybe_fast_result
        
        maybe_slow_result = self._get_slow_article(query)
        if isinstance(maybe_slow_result, Article):
            return maybe_slow_result
        
        maybe_extra_result = self._get_extra_article(query)
        if isinstance(maybe_extra_result, Article):
            return maybe_extra_result
        
        return None

    def __call__(self, query:str) -> None | Article:
        while self.locked:
            time.sleep(1)
        
        self.locked = True
        result = self._perform_search(query)
        self.locked = False
        return result

    def close(self):
        """
        Clean up index & zim
        """
        self.db.close()
        self.zim.close()

if __name__ == "__main__":

    searcher = Searcher("zim_data/wikipedia_en_simple_all_mini_2024-06.zim", "zim_data/wikipedia_en_simple_all_mini_2024-06.index")
    while True:
        result = searcher(input("Enter search term >"))
        if not result is None:
            print(f"Query took {result.query_duration * 1000:.1f}ms")
            print(result.summary)
        else:
            print("No results found")
        
        print("")
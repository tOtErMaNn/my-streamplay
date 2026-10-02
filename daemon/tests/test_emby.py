"""Drives the Emby backend against a scripted HTTP server, so no Emby is needed.
Run with ``python3 tests/test_emby.py`` from ``daemon``.
"""

from __future__ import annotations

import asyncio
import json
import pathlib
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from streamplay.backends.base import BackendError
from streamplay.backends.emby import EmbyBackend

FAILURES: list[str] = []

TOKEN = "emby-tok"
USER = "emby-user"


def check(label: str, condition: bool) -> None:
    print(("PASS  " if condition else "FAIL  ") + label)
    if not condition:
        FAILURES.append(label)


class FakeEmby(BaseHTTPRequestHandler):
    requests: list[tuple[str, str, dict]] = []

    def log_message(self, *args) -> None:
        pass

    def _reply(self, status: int, payload=None) -> None:
        data = json.dumps(payload).encode() if payload is not None else b""
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _handle(self, method: str) -> None:
        url = urlsplit(self.path)
        length = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(length)) if length else {}
        self.requests.append((method, url.path, body))
        query = parse_qs(url.query)

        if not url.path.startswith("/emby/") or self.headers.get("Authorization"):
            return self._reply(404)
        path = url.path[len("/emby"):]
        auth = self.headers.get("X-Emby-Authorization") or ""
        if path == "/Users/AuthenticateByName":
            if not auth.startswith("MediaBrowser ") or body.get("Pw") != "secret":
                return self._reply(401)
            return self._reply(200, {"AccessToken": TOKEN, "User": {"Id": USER}})
        if self.headers.get("X-Emby-Token") != TOKEN:
            return self._reply(401)
        if method == "POST":
            return self._reply(204)
        t1 = {"Id": "t1", "Name": "One", "Type": "Audio", "AlbumId": "al1",
              "RunTimeTicks": 1_200_000_000}
        t2 = {"Id": "t2", "Name": "Two", "Type": "Audio", "AlbumId": "al1",
              "RunTimeTicks": 600_000_000}
        t3 = {"Id": "t3", "Name": "Three", "Type": "Audio", "AlbumId": "al2",
              "RunTimeTicks": 600_000_000}
        ar1 = {"Id": "ar1", "Name": "Neon"}
        ar2 = {"Id": "ar2", "Name": "Blip"}
        al1 = {"Id": "al1", "Name": "Neon Lights", "ProductionYear": 2020}
        al2 = {"Id": "al2", "Name": "Blip Beeps", "ProductionYear": 2021}
        if path == "/Items":
            parent = (query.get("ParentId") or [""])[0]
            include = (query.get("IncludeItemTypes") or [""])[0]
            if include == "MusicAlbum":
                genre = (query.get("Genres") or [""])[0]
                term = (query.get("SearchTerm") or [""])[0].lower()
                if genre:
                    # genre_albums(): ParentId keeps them inside the library.
                    found = {("", "Pop"): [al1, al2],
                             ("lib1", "Pop"): [al1],
                             ("lib2", "Pop"): [al2],
                             ("", "Techno"): [al2],
                             ("lib1", "Techno"): [],
                             ("lib2", "Techno"): [al2]}
                    return self._reply(200,
                                       {"Items": found.get((parent, genre), [])})
                if term:
                    found = {("", "n"): [al1], ("lib1", "n"): [al1],
                             ("lib2", "n"): []}
                    return self._reply(200,
                                       {"Items": found.get((parent, term), [])})
                found = {"": [al1, al2], "lib1": [al1], "lib2": [al2]}
                return self._reply(200, {"Items": found.get(parent, [])})
            if include == "Audio":
                term = (query.get("SearchTerm") or [""])[0].lower()
                if term:
                    found = {("", "n"): [t1], ("lib1", "n"): [t1],
                             ("lib2", "n"): []}
                    return self._reply(200,
                                       {"Items": found.get((parent, term), [])})
                found = {"": [t1, t2, t3], "lib1": [t1, t2], "lib2": [t3],
                         "al1": [t1], "f1": [t1, t2], "f3": [t3]}
                return self._reply(200, {"Items": found.get(parent, [])})
            listing = {
                "": [{"Id": "lib1", "Name": "Music",
                      "CollectionType": "music"},
                     {"Id": "lib2", "Name": "More Music",
                      "CollectionType": "music"}],
                "lib1": [{"Id": "fv1", "Name": "Folders", "Type": "Folder"}],
                "lib2": [{"Id": "f3", "Name": "Extras", "Type": "Folder",
                          "ChildCount": 1}],
                "fv1": [{"Id": "f1", "Name": "Albums", "Type": "Folder",
                         "ChildCount": 2},
                        {"Id": "f2", "Name": "Singles", "Type": "Folder",
                         "ChildCount": 1},
                        t1],
                "f1": [t1, t2],
                "f3": [t3],
            }
            return self._reply(200, {"Items": listing.get(parent, [])})
        if path == "/Artists/AlbumArtists":
            parent = (query.get("ParentId") or [""])[0]
            found = {"": [ar1, ar2], "lib1": [ar1], "lib2": [ar2]}
            return self._reply(200, {"Items": found.get(parent, [])})
        if path == "/Artists":
            parent = (query.get("ParentId") or [""])[0]
            term = (query.get("SearchTerm") or [""])[0].lower()
            found = {("", "n"): [ar1], ("lib1", "n"): [ar1],
                     ("lib2", "n"): []}
            return self._reply(200, {"Items": found.get((parent, term), [])})
        if path == "/Genres":
            parent = (query.get("ParentId") or [""])[0]
            found = {"": [{"Name": "Pop"}, {"Name": "Techno"}],
                     "lib1": [{"Name": "Pop"}],
                     "lib2": [{"Name": "Techno"}]}
            return self._reply(200, {"Items": found.get(parent, [])})
        self._reply(200, {"Items": [t1]})

    def do_GET(self) -> None:
        self._handle("GET")

    def do_POST(self) -> None:
        self._handle("POST")


async def main() -> None:
    server = ThreadingHTTPServer(("127.0.0.1", 0), FakeEmby)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    root = f"http://127.0.0.1:{server.server_address[1]}"
    profile = {"id": "emby", "type": "emby", "url": root,
               "username": "roland", "password": "secret"}

    try:
        check("the /emby path is added once",
              EmbyBackend(dict(profile, url=root + "/emby/")).base == root + "/emby")

        bad = EmbyBackend(dict(profile, password="wrong"))
        try:
            await bad.connect()
            check("a wrong password is refused", False)
        except BackendError:
            check("a wrong password is refused", True)
        await bad.close()

        emby = EmbyBackend(profile)
        await emby.connect()
        check("login yields token and user", (emby.token, emby.user_id) == (TOKEN, USER))
        check("artists", [a.name for a in await emby.artists()]
              == ["Neon", "Blip"])
        tracks = await emby.album_tracks("al1")
        check("tracks", [(t.id, t.duration, t.backend) for t in tracks]
              == [("t1", 120.0, "emby")])

        check("emby can browse folders", emby.has_folders)
        libraries, direct = await emby.folder_items()
        check("folders start at the music libraries",
              [f["id"] for f in libraries] == ["lib1", "lib2"]
              and direct == [])
        subfolders, direct = await emby.folder_items("lib1")
        check("a library's folders hide behind its folder view",
              [f["id"] for f in subfolders] == ["f1", "f2"]
              and [t.id for t in direct] == ["t1"])
        subfolders, direct = await emby.folder_items("lib2")
        check("a library without a folder view lists its folders directly",
              [f["id"] for f in subfolders] == ["f3"] and direct == [])
        subfolders, direct = await emby.folder_items("f1")
        check("a folder lists its tracks", subfolders == []
              and [t.id for t in direct] == ["t1", "t2"])
        check("folder tracks are gathered recursively",
              [t.id for t in await emby.folder_tracks("f1")] == ["t1", "t2"])
        check("a library's tracks are gathered recursively",
              [t.id for t in await emby.folder_tracks("lib2")] == ["t3"])

        check("artists can be scoped to a library",
              [a.name for a in await emby.artists(library_id="lib2")]
              == ["Blip"])
        check("albums can be scoped to a library",
              [a.id for a in await emby.albums()] == ["al1", "al2"]
              and [a.id for a in await emby.albums(library_id="lib2")]
              == ["al2"])
        check("genres can be scoped to a library",
              await emby.genres() == ["Pop", "Techno"]
              and await emby.genres(library_id="lib1") == ["Pop"])
        check("genre albums stay inside the library",
              [a.id for a in await emby.genre_albums("Pop", library_id="lib1")]
              == ["al1"])
        found = await emby.search("n", library_id="lib1")
        check("search can be scoped to a library",
              [a.id for a in found["artists"]] == ["ar1"]
              and [a.id for a in found["albums"]] == ["al1"]
              and [t.id for t in found["tracks"]] == ["t1"]
              and (await emby.search("n", library_id="lib2"))["albums"] == [])
        stream = urlsplit(emby.stream_url(tracks[0]))
        check("stream goes through /emby with the token",
              stream.path == "/emby/Audio/t1/stream"
              and parse_qs(stream.query).get("api_key") == [TOKEN])

        cover_url, _, headers = emby.cover_request("al1", 128)
        check("cover request carries Emby's headers",
              cover_url == root + "/emby/Items/al1/Images/Primary"
              and headers.get("X-Emby-Token") == TOKEN
              and "Authorization" not in headers)

        await emby.scrobble(tracks[0], submission=True)
        check("a play is reported", ("POST", "/emby/Sessions/Playing/Stopped")
              in [(m, p) for m, p, _ in FakeEmby.requests])
        await emby.close()
        check("close logs out", ("POST", "/emby/Sessions/Logout")
              in [(m, p) for m, p, _ in FakeEmby.requests])
    finally:
        server.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
    if FAILURES:
        print(f"\n{len(FAILURES)} check(s) failed")
        sys.exit(1)
    print("\nall checks passed")

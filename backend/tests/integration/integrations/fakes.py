"""In-memory ListenBrainz, Spotify, YouTube and MusicBrainz servers (httpx MockTransport).

They implement just the endpoints TASTIFY calls, following the providers' documented request
and response shapes (INTEGRATIONS.md), record every call, and can be told to fail.
"""

import json
import uuid
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import parse_qs

import httpx

Json = dict[str, Any]


def _json(data: Any, status: int = 200) -> httpx.Response:
    return httpx.Response(status, json=data)


@dataclass
class FakeListenBrainz:
    token: str = "lb-token-0123456789"  # noqa: S105 - fake credential
    user: str = "lb_listener"
    listens: list[Json] = field(default_factory=list)
    playlists: dict[str, Json] = field(default_factory=dict)
    calls: list[str] = field(default_factory=list)
    fail_add: int = 0  # the next N item/add calls answer 500
    down: bool = False

    def listen(self, at: int, artist: str, title: str, **extra: Any) -> None:
        metadata: Json = {"artist_name": artist, "track_name": title, "additional_info": {}}
        if "mbid" in extra:
            metadata["mbid_mapping"] = {"recording_mbid": extra["mbid"]}
        if "isrc" in extra:
            metadata["additional_info"]["isrc"] = extra["isrc"]
        self.listens.append(
            {"listened_at": at, "recording_msid": str(uuid.uuid4()), "track_metadata": metadata}
        )

    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path.removeprefix("/1/")
        self.calls.append(f"{request.method} {path}")
        if self.down:
            return _json({"error": "down"}, 503)
        if request.headers.get("Authorization") != f"Token {self.token}":
            if path == "validate-token":
                return _json({"code": 200, "message": "Token invalid.", "valid": False})
            return _json({"error": "unauthorized"}, 401)
        if path == "validate-token":
            return _json({"code": 200, "valid": True, "user_name": self.user})
        if path == f"user/{self.user}/listens":
            params = request.url.params
            listens = sorted(self.listens, key=lambda x: -x["listened_at"])
            if "max_ts" in params:
                listens = [x for x in listens if x["listened_at"] < int(params["max_ts"])]
            count = int(params.get("count", 25))
            page = listens[:count]
            return _json({"payload": {"count": len(page), "user_id": self.user, "listens": page}})
        if path == f"user/{self.user}/playlists":
            return _json({"playlists": [{"playlist": p} for p in self.playlists.values()]})
        if path == "playlist/create":
            body = json.loads(request.content)["playlist"]
            assert body["extension"]["https://musicbrainz.org/doc/jspf#playlist"]["public"] is False
            mbid = str(uuid.uuid4())
            self.playlists[mbid] = {
                "identifier": f"https://listenbrainz.org/playlist/{mbid}",
                "title": body["title"],
                "annotation": body.get("annotation", ""),
                "track": [],
            }
            return _json({"status": "ok", "playlist_mbid": mbid})
        parts = path.split("/")
        if parts[0] == "playlist" and len(parts) >= 2:
            playlist = self.playlists.get(parts[1])
            if playlist is None:
                return _json({"error": "not found"}, 404)
            action = "/".join(parts[2:])
            if action == "":
                return _json({"playlist": playlist})
            if action == "item/delete":
                body = json.loads(request.content)
                del playlist["track"][body["index"] : body["index"] + body["count"]]
                return _json({"status": "ok"})
            if action == "item/add":
                if self.fail_add > 0:
                    self.fail_add -= 1
                    return _json({"error": "boom"}, 500)
                tracks = json.loads(request.content)["playlist"]["track"]
                assert len(tracks) <= 100
                for track in tracks:
                    (identifier,) = track["identifier"]
                    assert identifier.startswith("https://musicbrainz.org/recording/")
                    playlist["track"].append({"identifier": identifier})
                return _json({"status": "ok"})
        return _json({"error": f"unexpected {path}"}, 404)

    def items(self, mbid: str) -> list[str]:
        return [t["identifier"].rsplit("/", 1)[-1] for t in self.playlists[mbid]["track"]]


@dataclass
class FakeSpotify:
    code: str = "spotify-code"
    access: str = "sp-access-1"
    refresh_token: str = "sp-refresh-1"  # noqa: S105 - fake credential
    saved: list[Json] = field(default_factory=list)
    recent: list[Json] = field(default_factory=list)
    catalogue: dict[str, str] = field(default_factory=dict)  # isrc -> spotify track id
    playlists: dict[str, Json] = field(default_factory=dict)
    calls: list[str] = field(default_factory=list)
    verifiers: list[str] = field(default_factory=list)
    refresh_fails: bool = False

    def handler(self, request: httpx.Request) -> httpx.Response:
        if request.url.host == "accounts.spotify.com":
            form = {k: v[0] for k, v in parse_qs(request.content.decode()).items()}
            self.calls.append(f"token {form['grant_type']}")
            if form["grant_type"] == "authorization_code":
                if form["code"] != self.code:
                    return _json({"error": "invalid_grant"}, 400)
                self.verifiers.append(form["code_verifier"])
            elif self.refresh_fails or form.get("refresh_token") != self.refresh_token:
                return _json({"error": "invalid_grant"}, 400)
            else:
                self.access = f"sp-access-{len(self.calls)}"
            return _json(
                {
                    "access_token": self.access,
                    "refresh_token": self.refresh_token,
                    "expires_in": 3600,
                    "scope": "user-library-read playlist-modify-private",
                }
            )
        path = request.url.path.removeprefix("/v1/")
        self.calls.append(f"{request.method} {path}")
        if request.headers.get("Authorization") != f"Bearer {self.access}":
            return _json({"error": {"status": 401}}, 401)
        params = request.url.params
        if path == "me":
            return _json({"id": "sp_user", "display_name": "Spotify Listener"})
        if path == "me/tracks":
            offset = int(params.get("offset", 0))
            return _json({"items": self.saved[offset : offset + 50], "next": None})
        if path == "me/player/recently-played":
            return _json({"items": self.recent})
        if path == "search":
            q = params["q"]
            items = []
            if q.startswith("isrc:") and q[5:] in self.catalogue:
                spotify_id = self.catalogue[q[5:]]
                items = [{"uri": f"spotify:track:{spotify_id}", "name": "x", "artists": []}]
            return _json({"tracks": {"items": items}})
        if path == "me/playlists" and request.method == "GET":
            return _json({"items": list(self.playlists.values()), "next": None})
        if path == "me/playlists" and request.method == "POST":
            body = json.loads(request.content)
            playlist_id = f"pl{len(self.playlists) + 1}"
            self.playlists[playlist_id] = {
                "id": playlist_id,
                "description": body["description"],
                "external_urls": {"spotify": f"https://open.spotify.com/playlist/{playlist_id}"},
                "items": [],
            }
            return _json(self.playlists[playlist_id], 201)
        parts = path.split("/")
        if parts[0] == "playlists":
            playlist = self.playlists.get(parts[1])
            if playlist is None:
                return _json({"error": {"status": 404}}, 404)
            if len(parts) == 2:
                return _json(playlist)
            uris = json.loads(request.content)["uris"]
            assert len(uris) <= 100
            if request.method == "PUT":
                playlist["items"] = list(uris)
            else:
                playlist["items"].extend(uris)
            return _json({"snapshot_id": "s"}, 201)
        return _json({"error": f"unexpected {path}"}, 404)


@dataclass
class FakeYouTube:
    code: str = "google-code"
    access: str = "yt-access"
    videos: dict[str, str] = field(default_factory=dict)  # "artist title" -> video id
    playlists: dict[str, Json] = field(default_factory=dict)
    calls: list[str] = field(default_factory=list)

    def handler(self, request: httpx.Request) -> httpx.Response:
        if request.url.host == "oauth2.googleapis.com":
            form = {k: v[0] for k, v in parse_qs(request.content.decode()).items()}
            self.calls.append(f"token {request.url.path}")
            if request.url.path == "/revoke":
                return _json({})
            assert form["client_secret"] == "google-secret"  # noqa: S105 - fake credential
            if form.get("code") not in (None, self.code):
                return _json({"error": "invalid_grant"}, 400)
            return _json(
                {"access_token": self.access, "refresh_token": "yt-refresh", "expires_in": 3600}
            )
        path = request.url.path.removeprefix("/youtube/v3/")
        params = request.url.params
        self.calls.append(f"{request.method} {path}")
        if request.headers.get("Authorization") != f"Bearer {self.access}":
            return _json({"error": {"code": 401}}, 401)
        if path == "channels":
            return _json({"items": [{"id": "UC123", "snippet": {"title": "My Channel"}}]})
        if path == "search":
            video = self.videos.get(params["q"])
            return _json({"items": [{"id": {"videoId": video}}] if video else []})
        if path == "playlists" and request.method == "GET":
            if "id" in params:
                found = [p for p in self.playlists.values() if p["id"] == params["id"]]
                return _json({"items": [{"id": p["id"]} for p in found]})
            return _json({"items": list(self.playlists.values())})
        if path == "playlists" and request.method == "POST":
            body = json.loads(request.content)
            assert body["status"]["privacyStatus"] == "private"
            playlist_id = f"PL{len(self.playlists) + 1}"
            self.playlists[playlist_id] = {
                "id": playlist_id,
                "snippet": body["snippet"],
                "items": [],
            }
            return _json({"id": playlist_id})
        if path == "playlistItems" and request.method == "GET":
            playlist = self.playlists[params["playlistId"]]
            return _json(
                {
                    "items": [
                        {"id": item_id, "snippet": {"resourceId": {"videoId": video}}}
                        for item_id, video in playlist["items"]
                    ]
                }
            )
        if path == "playlistItems" and request.method == "POST":
            snippet = json.loads(request.content)["snippet"]
            playlist = self.playlists[snippet["playlistId"]]
            item = (f"item{len(self.calls)}", snippet["resourceId"]["videoId"])
            playlist["items"].insert(min(snippet["position"], len(playlist["items"])), item)
            return _json({"id": item[0]})
        if path == "playlistItems" and request.method == "DELETE":
            for playlist in self.playlists.values():
                playlist["items"] = [i for i in playlist["items"] if i[0] != params["id"]]
            return httpx.Response(204)
        return _json({"error": f"unexpected {path}"}, 404)


@dataclass
class FakeMusicBrainz:
    recordings: list[Json] = field(default_factory=list)
    queries: list[str] = field(default_factory=list)

    def handler(self, request: httpx.Request) -> httpx.Response:
        assert "TASTIFY" in request.headers["User-Agent"]
        self.queries.append(request.url.params["query"])
        return _json({"recordings": self.recordings})

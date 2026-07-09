"""build_index_stats: sums only the profile asset's downloads; degrades per-entry."""

from __future__ import annotations

import json
import shutil
import tempfile
import unittest
import urllib.request
from pathlib import Path

import build_index_stats


class BuildIndexStatsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.index = self.tmp / "index.json"
        self.index.write_text(
            json.dumps(
                {
                    "profiles": [
                        {"name": "p", "url": "git+https://github.com/o/r.git@v1.0.0"},
                        {"name": "elsewhere", "url": "git+https://gitlab.com/o/r.git@v1"},
                    ]
                }
            ),
            encoding="utf-8",
        )
        self.out = self.tmp / "stats.json"

    def _serve(self, responses: dict[str, object]) -> None:
        class _Resp:
            def __init__(self, data: bytes) -> None:
                self._d = data

            def read(self, n: int) -> bytes:
                return self._d

            def __enter__(self):
                return self

            def __exit__(self, *a: object) -> None: ...

        def fake_urlopen(req, timeout=None):
            path = req.full_url.removeprefix("https://api.github.com")
            return _Resp(json.dumps(responses[path]).encode())

        self._orig = urllib.request.urlopen
        urllib.request.urlopen = fake_urlopen
        self.addCleanup(lambda: setattr(urllib.request, "urlopen", self._orig))

    def test_sums_only_the_profile_asset_across_releases(self) -> None:
        self._serve(
            {
                "/repos/o/r": {"stargazers_count": 12, "forks_count": 3},
                "/repos/o/r/releases?per_page=100": [
                    {
                        "assets": [
                            {"name": "agent-native-profile.tar.gz", "download_count": 300},
                            {"name": "unrelated.zip", "download_count": 999},
                        ]
                    },
                    {"assets": [{"name": "agent-native-profile.tar.gz", "download_count": 40}]},
                ],
            }
        )
        rc = build_index_stats.main(["--index", str(self.index), "--out", str(self.out)])
        self.assertEqual(rc, 0)
        data = json.loads(self.out.read_text(encoding="utf-8"))
        self.assertEqual(data["profiles"]["p"], {"stars": 12, "forks": 3, "downloads": 340})
        self.assertNotIn("elsewhere", data["profiles"])  # non-GitHub: no public stats

    def test_wholly_unreachable_api_is_a_visible_failure(self) -> None:
        def broken(req, timeout=None):
            raise OSError("api down")

        self._orig = urllib.request.urlopen
        urllib.request.urlopen = broken
        self.addCleanup(lambda: setattr(urllib.request, "urlopen", self._orig))
        rc = build_index_stats.main(["--index", str(self.index), "--out", str(self.out)])
        self.assertEqual(rc, 1)  # red scheduled run, not a silently empty stats file


if __name__ == "__main__":
    unittest.main()

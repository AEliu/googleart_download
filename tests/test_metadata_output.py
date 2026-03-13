from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from googleart_download.metadata import metadata_to_dict, write_metadata_sidecar
from googleart_download.models import ArtworkMetadata
from googleart_download.metadata.parsers import parse_artwork_metadata


class MetadataOutputTests(unittest.TestCase):
    def test_parse_artwork_metadata_extracts_core_fields(self) -> None:
        html = """
        <script type="application/ld+json">
        [{"@type":"CreativeWork","name":"Artwork Title","author":"Artist Name","description":"Long description","url":"https://example.com/art"}]
        </script>
        ["Date Created",[["1890"]],0]
        ["Rights",[["Museum Rights"]],0]
        ["External Link",[["Museum page","https://museum.example"]],0]
        """

        metadata = parse_artwork_metadata(html, fallback_url="https://fallback", fallback_title="Fallback")

        self.assertEqual(metadata.title, "Artwork Title")
        self.assertEqual(metadata.creator, "Artist Name")
        self.assertEqual(metadata.description, "Long description")
        self.assertEqual(metadata.source_url, "https://example.com/art")
        self.assertEqual(metadata.date_created, "1890")
        self.assertEqual(metadata.rights, "Museum Rights")
        self.assertEqual(metadata.external_link, "Museum page")

    def test_write_metadata_sidecar_outputs_json(self) -> None:
        metadata = ArtworkMetadata(
            title="Artwork Title",
            creator="Artist Name",
            description="Description",
            source_url="https://example.com/art",
        )

        with TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "artwork.jpg"
            output_path.write_bytes(b"fake")
            sidecar = write_metadata_sidecar(output_path, metadata)
            payload = json.loads(sidecar.read_text(encoding="utf-8"))

        self.assertEqual(payload["title"], "Artwork Title")
        self.assertEqual(payload["creator"], "Artist Name")
        self.assertEqual(payload["description"], "Description")
        self.assertEqual(payload["source_url"], "https://example.com/art")
        self.assertEqual(sidecar.name, "artwork.jpg.json")

    def test_metadata_to_dict_omits_empty_values(self) -> None:
        payload = metadata_to_dict(ArtworkMetadata(title="Title", creator=None, description=""))
        self.assertEqual(payload, {"title": "Title"})


if __name__ == "__main__":
    unittest.main()

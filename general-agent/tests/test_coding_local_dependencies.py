"""Real offline local package installation from approved fixture artifacts."""

import hashlib
import io
import json
import zipfile

import pytest

from general_agent.coding.local_runtime import LocalRuntime, local_toolchain
from general_agent.coding.setup import SetupManager
from general_agent.processes import BinaryProcessResult, ProcessResult
from general_agent.workspace import corp_storage_key
from tests.test_coding_setup import FakeAcquisition, archive


def wheel():
    content = io.BytesIO()
    with zipfile.ZipFile(content, "w") as package:
        package.writestr("example/__init__.py", 'VALUE = "offline fixture"\n')
        package.writestr("example-1.0.dist-info/METADATA", "Metadata-Version: 2.1\nName: example\nVersion: 1.0\n")
        package.writestr("example-1.0.dist-info/WHEEL", "Wheel-Version: 1.0\nGenerator: fixture\nRoot-Is-Purelib: true\nTag: py3-none-any\n")
        package.writestr("example-1.0.dist-info/RECORD", "example/__init__.py,,\nexample-1.0.dist-info/METADATA,,\nexample-1.0.dist-info/WHEEL,,\nexample-1.0.dist-info/RECORD,,\n")
    return content.getvalue()


@pytest.mark.parametrize("kind", ["python", "node"])
async def test_approved_artifacts_install_into_private_runtime_and_survive_source_sync(settings, kind):
    if kind == "node" and not local_toolchain(settings)["node"]:
        pytest.skip("Node.js is an optional host tool.")
    corp, sid = "A123456", "a" * 32
    repo = settings.coding_root / corp_storage_key(corp) / sid / "repo"
    repo.mkdir(parents=True)
    data = wheel()
    requirements = b"example==1.0 --hash=sha256:" + hashlib.sha256(data).hexdigest().encode() + b"\n"
    if kind == "python":
        (repo / "requirements.txt").write_bytes(requirements)
        artifact = archive({"requirements.txt": requirements, "wheels/example-1.0-py3-none-any.whl": data})
        command = "python -c 'import example; print(example.VALUE)'"
    else:
        (repo / "package.json").write_text('{"name":"project","dependencies":{"example":"1.0.0"}}')
        (repo / "package-lock.json").write_text(json.dumps({"lockfileVersion": 3, "packages": {
            "": {"name": "project"}, "node_modules/example": {"version": "1.0.0",
                "resolved": "https://registry.npmjs.org/example/-/example-1.0.0.tgz", "integrity": "sha512-YWJjZA=="}}}))
        artifact = archive({"node_modules/example/package.json": b'{"name":"example","version":"1.0.0","type":"module","exports":"./index.js"}',
                            "node_modules/example/index.js": b'export const value = "offline fixture";\n'})
        command = 'node --input-type=module -e \'import {value} from "example"; console.log(value)\''
    (repo / "main.txt").write_text("Original source")
    runtime = LocalRuntime(settings, repo, "b" * 32)
    await runtime.start()

    class ArtifactAcquisition(FakeAcquisition):
        async def start(self):
            self.runtime_id = runtime.runtime_id

        async def package_bytes(self, action, *args, **kwargs):
            assert action == "package-export"
            return BinaryProcessResult(artifact, b"", 0, False)

        async def _package_controller(self, *args, **kwargs):
            return ProcessResult("Prepared fixture artifact", 0, False)

    try:
        before = runtime.identity
        record = await SetupManager(settings, runtime_factory=ArtifactAcquisition).prepare(corp, sid, repo, kind)
        assert record["status"] == "ready", record
        await runtime.install_setup(record)
        assert runtime.identity != before
        await runtime.sync_to_runtime()
        result = await runtime.execute(command, timeout=10)
        assert result.exit_code == 0 and result.output == "offline fixture", result
        (repo / "main.txt").write_text("Updated source")
        await runtime.sync_to_runtime()
        result = await runtime.execute(command, timeout=10)
        assert result.exit_code == 0 and result.output == "offline fixture", result
        assert not (repo / "node_modules").exists()
        assert not (repo / "example").exists()
    finally:
        await runtime.close()

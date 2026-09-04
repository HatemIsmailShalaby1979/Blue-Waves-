from pathlib import Path

from blue_waves.cloud_gpu_orchestrator import CloudGpuOrchestrator


class FakeAdapter:
    name = "fake_gpu"

    def __init__(self):
        self.state = "queued"

    def submit(self, request):
        self.state = "running"
        return "remote-1"

    def status(self, remote_job_id):
        return {"status": self.state}

    def cancel(self, remote_job_id):
        self.state = "cancelled"

    def download(self, remote_job_id, target: Path):
        target.write_bytes(b"valid-artifact")
        self.state = "completed"
        return target


def test_cloud_gpu_job_requires_explicit_poll_and_validated_artifact(tmp_path):
    adapter = FakeAdapter()
    orchestrator = CloudGpuOrchestrator(tmp_path, {adapter.name: adapter})
    job = orchestrator.submit(adapter.name, "music", {"prompt": "ambient"})
    assert job.status == "submitted"
    assert orchestrator.poll(job.job_id).status == "running"

    adapter.state = "completed"
    assert orchestrator.poll(job.job_id).status == "completed"
    finished = orchestrator.retrieve(job.job_id, tmp_path / "artifact.bin")
    assert finished.status == "artifact_validated"
    assert finished.artifact_sha256

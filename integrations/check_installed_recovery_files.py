"""Compare installed recovery inputs with the previous readback and reviewed release archives."""
import argparse
import hashlib
import json
from pathlib import Path
from zipfile import ZipFile


def require(condition, message):
    if not condition:
        raise ValueError(message)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def json_file(path):
    return json.loads(path.read_bytes())


def verify(baseline, release_zip, backup, source_root, *, static_followup=None):
    prior = json_file(baseline)
    require(prior.get("schema") == "mesh/installed-recovery-file-readback/v1", "Unknown prior readback")
    root = source_root.resolve(strict=True)
    manifest = json_file(backup / "manifest.json")
    require(root == Path(prior["sourceRoot"]).resolve() == Path(manifest["sourceRoot"]).resolve(),
            "Backup and baseline must identify the installed checkout")
    archive = manifest["archives"]["source"]
    source_zip = (backup / archive["file"]).resolve(strict=True)
    require(source_zip.is_relative_to(backup.resolve()), "Source archive is outside its backup")
    with source_zip.open("rb") as stream:
        require(hashlib.file_digest(stream, "sha256").hexdigest() == archive["sha256"], "Source archive changed")
    sources = dict(prior["sourceSha256"])
    runtime = {}
    replacements = []
    with ZipFile(release_zip) as release, ZipFile(source_zip) as snapshot:
        for bundle in (release, snapshot):
            require(len(set(bundle.namelist())) == len(bundle.namelist()), "Repeated archive entry")
        def reviewed(name):
            return json.loads(release.read(name))

        change = reviewed("source-readback.json")
        if prior.get("releaseCommit"):
            if "installedBase" in change:
                require(prior["releaseCommit"].startswith(change["installedBase"]), "Unexpected preceding release")
            else:
                inputs = reviewed("release-inputs.json")
                require(inputs["commit"] == change["commit"] and inputs["files"] == change["changed"]
                        and inputs["backupDirectory"] == change["backupDirectory"],
                        "Release inputs disagree with source readback")
                require(inputs["installedBase"] == prior["releaseCommit"], "Unexpected preceding release")
        files = change["changed"]
        require(files == reviewed("owner-review/overlay.review.json")["proposedPlan"]["files"],
                "Release source records disagree")
        changes = {row["relativePath"]: row for row in files}
        require(len(changes) == len(files), "Duplicate release source")
        if static_followup is not None:
            asset = "public/app.js"
            require(isinstance(static_followup, dict) and static_followup.get("path") == asset and
                    asset in changes and asset not in sources,
                    "Static follow-up must be the unpinned browser entry")
            require(static_followup.get("before") == changes[asset]["afterSha256"] and
                    static_followup.get("after") != static_followup["before"],
                    "Static follow-up does not extend the reviewed release")
        changed_sources = []
        for rel in sorted(sources.keys() | changes.keys()):
            path = (root / rel).resolve(strict=True)
            require(path.is_relative_to(root), "Source outside installed checkout")
            if rel in changes:
                row = changes[rel]
                if rel in sources:
                    require(row["beforeSha256"] == sources[rel], f"Unreviewed starting bytes: {rel}")
                    changed_sources.append(rel)
                expected = row["afterSha256"]
            else:
                expected = sources[rel]
            if static_followup is not None and rel == asset:
                expected = static_followup["after"]
            require(digest(path.read_bytes()) == expected == digest(snapshot.read(rel)),
                    f"Installed source, release or backup mismatch: {rel}")
            if rel in sources:
                sources[rel] = expected
        for role, old in prior["runtimeFiles"].items():
            label = "wrapper" if role == "hiddenWrapper" else role
            entry = f"owner-review/{label}.review.json"
            if entry in release.namelist():
                body = reviewed(entry)
                record = {"path": body["targetPath"], "sha256": body["expectedSha256"]}
            else:
                record = old
            require(digest(Path(record["path"]).read_bytes()) == record["sha256"],
                    f"Installed startup record mismatch: {role}")
            if record != old:
                replacements.append(role)
            runtime[role] = record

    def body(role):
        return json_file(Path(runtime[role]["path"]))

    def link(record, field, checksum, role):
        require(Path(record[field]) == Path(runtime[role]["path"]) and
                record[checksum] == runtime[role]["sha256"], f"Startup reference mismatch: {role}")

    startup = body("startup-approval")
    for role in ("handoff", "memory"):
        link(startup, role+"ApprovalPath", role+"ApprovalSha256", role+"-approval")
    handoff = body("handoff-approval")
    for mode, permission in (("capture", "capture-approval"), ("connected", "reader-approval")):
        link(handoff[mode], "profilePath", "profileSha256", mode+"-gateway")
        link(handoff[mode], "approvalPath", "approvalSha256", permission)
    link(handoff["connected"], "projectApprovalPath", "projectApprovalSha256", "service-only-approval")
    memory = body("memory-approval")
    link(memory, "profilePath", "profileSha256", "connected-gateway")
    link(memory, "readerServiceProfile", "readerServiceSha256", "reader-service")
    connected = body("connected-gateway")
    for profile in (connected, body("fallback-gateway")):
        link(profile, "readerProfile", "readerProfileSha256", "reader-runtime")
    link(connected["projectSync"], "serviceProfile", "serviceProfileSha256", "writer-service")
    wrapper = Path(runtime["hiddenWrapper"]["path"]).read_text(encoding="utf-16")
    approval = runtime["startup-approval"]
    require(wrapper.count(f'--approval {approval["path"]} --sha256 {approval["sha256"]}') == 1,
            "Wrapper does not point to the expected startup record")
    return dict(schema=prior["schema"], approved=False, sourceRoot=str(root),
                sourceSha256=sources, sourceArchiveSha256=archive["sha256"], runtimeFiles=runtime,
                releaseCommit=change["commit"], changedRecoverySources=changed_sources,
                replacedRoles=sorted(replacements), retainedQueueInspected=False, liveJobStateChanged=False)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("baseline", "reviewed_release_zip", "installed_backup_directory", "source_root"):
        parser.add_argument(name, type=Path)
    parser.add_argument("--static-followup", type=Path,
                        help="Reviewed browser-only delta installed after the main release")
    args = parser.parse_args()
    print(json.dumps(verify(args.baseline, args.reviewed_release_zip, args.installed_backup_directory,
                            args.source_root, static_followup=json_file(args.static_followup)
                            if args.static_followup else None), indent=2))

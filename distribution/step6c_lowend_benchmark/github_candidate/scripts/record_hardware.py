"""Record CPU identification without requiring a PowerShell script policy change."""
import argparse
import json
import os
from pathlib import Path
import subprocess


def query_cpu():
    command = (
        "$ErrorActionPreference='Stop'; "
        "$cpus=@(Get-CimInstance Win32_Processor); "
        "if (!$cpus.Count) {throw 'No processor data'}; "
        "[Console]::OutputEncoding=[Text.Encoding]::UTF8; "
        "@($cpus | Select-Object Name,NumberOfCores,NumberOfLogicalProcessors)|ConvertTo-Json -Compress"
    )
    result = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command],
                            check=True, encoding="utf-8", stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    payload = json.loads(result.stdout)
    entries = payload if isinstance(payload, list) else [payload]
    return dict(cpu_model=" / ".join(dict.fromkeys(cpu["Name"].strip() for cpu in entries)),
                physical_cores=sum(cpu["NumberOfCores"] for cpu in entries),
                logical_processors_cim=sum(cpu["NumberOfLogicalProcessors"] for cpu in entries),
                source="Windows Win32_Processor")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cpu-model")
    parser.add_argument("--physical-cores", type=int)
    args = parser.parse_args()
    if args.cpu_model or args.physical_cores is not None:
        if not args.cpu_model or args.physical_cores is None:
            parser.error("Supply both --cpu-model and --physical-cores for manual input.")
        record = dict(cpu_model=args.cpu_model, physical_cores=args.physical_cores, source="operator supplied")
    else:
        try:
            record = query_cpu()
        except (OSError, ValueError, KeyError, subprocess.CalledProcessError):
            parser.error("Windows CIM unavailable. Read CPU name and cores in Task Manager and use the manual options.")
    if not 0 < record["physical_cores"] <= (os.cpu_count() or 0):
        parser.error("Physical core count must be positive and within the available logical CPU count.")
    record["note"] = "Offline throughput. Record power plan and background load in private run notes."
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(record, stream, ensure_ascii=False, indent=2)
        stream.write("\n")


if __name__ == "__main__":
    main()

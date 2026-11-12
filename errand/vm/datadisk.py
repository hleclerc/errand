"""The data disk: a second drive in the guest, formatted on first use, flushed before a stop.
"""
from __future__ import annotations


DATA_DRIVE = "E"

# Run in the guest once it answers, every boot: the disk that is kept made
# usable. Windows Server leaves a disk it has not seen offline ( its SAN
# policy ), a new one is blank, and a letter is not promised from one boot to
# the next -- so each is seen to. The system disk is the boot one; the kept
# one is the other.
DATA_SCRIPT = f"""
$ErrorActionPreference = 'Stop'
$d = Get-Disk | Where-Object {{ -not $_.IsBoot -and -not $_.IsSystem }} | Select-Object -First 1
if ( -not $d ) {{ throw 'no data disk' }}
if ( $d.IsOffline )  {{ Set-Disk -Number $d.Number -IsOffline $false }}
if ( $d.IsReadOnly ) {{ Set-Disk -Number $d.Number -IsReadOnly $false }}
if ( ( Get-Disk -Number $d.Number ).PartitionStyle -eq 'RAW' ) {{
    Initialize-Disk -Number $d.Number -PartitionStyle GPT
    New-Partition -DiskNumber $d.Number -UseMaximumSize -DriveLetter {DATA_DRIVE} | Out-Null
    Format-Volume -DriveLetter {DATA_DRIVE} -FileSystem NTFS -NewFileSystemLabel errand-data -Confirm:$false | Out-Null
}} else {{
    $p = Get-Partition -DiskNumber $d.Number | Where-Object Type -eq 'Basic' | Select-Object -First 1
    if ( $p.DriveLetter -ne '{DATA_DRIVE}' ) {{
        Set-Partition -DiskNumber $d.Number -PartitionNumber $p.PartitionNumber -NewDriveLetter {DATA_DRIVE}
    }}
}}
# Scanned on every write otherwise, which halves a compiler's speed -- as for C:\\errand.
try {{ Add-MpPreference -ExclusionPath {DATA_DRIVE}:\\ }} catch {{ }}
Write-Output 'errand-data-ok'
"""


# What Windows has not written yet, written. The machine is thrown away rather
# than shut down, which to the disk that is kept is a power cut: without this
# the files of the last command are there, with their names and sizes, and
# zeros inside.
FLUSH_SCRIPT = f"Write-VolumeCache -DriveLetter {DATA_DRIVE}"


def powershell( script: str ) -> str:
    """`script` as one cmd.exe line: encoded, so that no quote or newline of it
    has to survive cmd.exe."""
    import base64
    return "powershell -NoProfile -NonInteractive -EncodedCommand " + \
           base64.b64encode( script.encode( "utf-16-le" ) ).decode()

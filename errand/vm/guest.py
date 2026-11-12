"""What the guest is given: the unattended answer file and the setup script ( MSVC, Python, more ).
"""
from __future__ import annotations

from pathlib import Path

from .transfer import GUEST_MSYS
from .common import USER


# Only ever typed at the console of a machine nobody looks at: sshd takes a key,
# and password logins are switched off before the port is ever reachable.
PASSWORD = "Errand-vm-1!"
VCVARS   = r"C:\BuildTools\VC\Auxiliary\Build\vcvars64.bat"
BUILD_TOOLS = "https://aka.ms/vs/17/release/vs_BuildTools.exe"


def autounattend( *, key = None, index = 1 ) -> str:
    """What Windows Setup reads instead of asking: one partition, the image at
    `index`, an Administrator who logs on once, and that logon running
    `errand-setup.ps1` from whichever drive carries it."""
    product = ( f"<ProductKey><Key>{key}</Key><WillShowUI>OnError</WillShowUI></ProductKey>"
                if key else "" )
    component = ( 'processorArchitecture="amd64" publicKeyToken="31bf3856ad364e35" '
                  'language="neutral" versionScope="nonSxS"' )
    # Windows 11 refuses to install without a TPM and Secure Boot; neither
    # matters to a compiler. Harmless on Server, which does not check.
    bypass = "".join(
        f'<RunSynchronousCommand wcm:action="add"><Order>{i}</Order>'
        f'<Path>reg add HKLM\\SYSTEM\\Setup\\LabConfig /v {what} /t REG_DWORD /d 1 /f</Path>'
        f'</RunSynchronousCommand>'
        for i, what in enumerate( ( "BypassTPMCheck", "BypassSecureBootCheck", "BypassRAMCheck" ), 1 ) )
    return f"""<?xml version="1.0" encoding="utf-8"?>
<unattend xmlns="urn:schemas-microsoft-com:unattend" xmlns:wcm="http://schemas.microsoft.com/WMIConfig/2002/State">
  <settings pass="windowsPE">
    <component name="Microsoft-Windows-International-Core-WinPE" {component}>
      <SetupUILanguage><UILanguage>en-US</UILanguage></SetupUILanguage>
      <InputLocale>en-US</InputLocale>
      <SystemLocale>en-US</SystemLocale>
      <UILanguage>en-US</UILanguage>
      <UserLocale>en-US</UserLocale>
    </component>
    <component name="Microsoft-Windows-Setup" {component}>
      <RunSynchronous>{bypass}</RunSynchronous>
      <DiskConfiguration>
        <Disk wcm:action="add">
          <DiskID>0</DiskID>
          <WillWipeDisk>true</WillWipeDisk>
          <CreatePartitions>
            <CreatePartition wcm:action="add"><Order>1</Order><Type>Primary</Type><Extend>true</Extend></CreatePartition>
          </CreatePartitions>
          <ModifyPartitions>
            <ModifyPartition wcm:action="add">
              <Order>1</Order><PartitionID>1</PartitionID><Active>true</Active>
              <Format>NTFS</Format><Label>Windows</Label><Letter>C</Letter>
            </ModifyPartition>
          </ModifyPartitions>
        </Disk>
      </DiskConfiguration>
      <ImageInstall>
        <OSImage>
          <InstallFrom><MetaData wcm:action="add"><Key>/IMAGE/INDEX</Key><Value>{index}</Value></MetaData></InstallFrom>
          <InstallTo><DiskID>0</DiskID><PartitionID>1</PartitionID></InstallTo>
        </OSImage>
      </ImageInstall>
      <UserData>
        <AcceptEula>true</AcceptEula>
        {product}
      </UserData>
    </component>
  </settings>
  <settings pass="specialize">
    <component name="Microsoft-Windows-Shell-Setup" {component}>
      <ComputerName>errand-win</ComputerName>
      <TimeZone>UTC</TimeZone>
    </component>
  </settings>
  <settings pass="oobeSystem">
    <component name="Microsoft-Windows-Shell-Setup" {component}>
      <UserAccounts>
        <AdministratorPassword><Value>{PASSWORD}</Value><PlainText>true</PlainText></AdministratorPassword>
      </UserAccounts>
      <AutoLogon>
        <Enabled>true</Enabled><Username>{USER}</Username><LogonCount>1</LogonCount>
        <Password><Value>{PASSWORD}</Value><PlainText>true</PlainText></Password>
      </AutoLogon>
      <OOBE>
        <HideEULAPage>true</HideEULAPage>
        <HideOnlineAccountScreens>true</HideOnlineAccountScreens>
        <HideWirelessSetupInOOBE>true</HideWirelessSetupInOOBE>
        <ProtectYourPC>3</ProtectYourPC>
      </OOBE>
      <FirstLogonCommands>
        <SynchronousCommand wcm:action="add">
          <Order>1</Order>
          <CommandLine>cmd /c for %d in (D E F G H I J K L M) do if exist %d:\\errand-setup.ps1 powershell -NoProfile -ExecutionPolicy Bypass -File %d:\\errand-setup.ps1</CommandLine>
          <Description>errand</Description>
        </SynchronousCommand>
      </FirstLogonCommands>
    </component>
  </settings>
</unattend>
"""


def setup_script( *, msvc = True, python = None, provision = ( ) ) -> str:
    """The first logon, unattended: sshd first ( so a failure further down can
    still be looked at ), then the tools, then a line saying how it went, then
    off -- the power going off is how the host knows the install is over."""
    steps = [ ]
    if msvc:
        steps.append( f"""
    Step 'msvc build tools'
    Invoke-WebRequest -UseBasicParsing '{BUILD_TOOLS}' -OutFile C:\\vs_buildtools.exe
    $p = Start-Process C:\\vs_buildtools.exe -Wait -PassThru -ArgumentList @(
        '--quiet', '--wait', '--norestart', '--nocache', '--installPath', 'C:\\BuildTools',
        '--add', 'Microsoft.VisualStudio.Workload.VCTools', '--includeRecommended' )
    if ( $p.ExitCode -ne 0 -and $p.ExitCode -ne 3010 ) {{ throw "build tools: exit $( $p.ExitCode )" }}
    Remove-Item C:\\vs_buildtools.exe""" )
    if python:
        steps.append( f"""
    Step 'python {python}'
    Invoke-WebRequest -UseBasicParsing 'https://www.python.org/ftp/python/{python}/python-{python}-amd64.exe' -OutFile C:\\python-setup.exe
    $p = Start-Process C:\\python-setup.exe -Wait -PassThru -ArgumentList @(
        '/quiet', 'InstallAllUsers=1', 'PrependPath=1', 'Include_test=0' )
    if ( $p.ExitCode -ne 0 ) {{ throw "python: exit $( $p.ExitCode )" }}
    Remove-Item C:\\python-setup.exe""" )
    # A label is a PowerShell string: a quote of the line it names would end it,
    # and the whole script with it. Doubled, it is a quote.
    label = lambda text: "'" + str( text ).replace( "'", "''" ) + "'"
    for i, p in enumerate( provision ):
        if isinstance( p, dict ):
            steps.append( f"\n    Step {label( 'provision: ' + p[ 'line' ][ : 40 ] )}\n    {p[ 'line' ]}" )
        else:
            steps.append( f"\n    Step {label( Path( p ).name )}\n    & ( Join-Path $media 'errand-provision-{i}.ps1' )" )
    return f"""$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
Start-Transcript -Path C:\\errand-setup.log
$media = Split-Path -Parent $MyInvocation.MyCommand.Path
function Step( $what ) {{ Write-Host "== $what" }}
New-Item -ItemType Directory -Force C:\\errand | Out-Null
try {{
    Step 'sshd'
    if ( -not ( Get-Service sshd -ErrorAction SilentlyContinue ) ) {{
        Add-WindowsCapability -Online -Name OpenSSH.Server~~~~0.0.1.0 | Out-Null
    }}
    Set-Service sshd -StartupType Automatic
    Start-Service sshd
    $keys = 'C:\\ProgramData\\ssh\\administrators_authorized_keys'
    Copy-Item ( Join-Path $media 'errand_key.pub' ) $keys
    icacls $keys /inheritance:r /grant '*S-1-5-32-544:F' /grant '*S-1-5-18:F' | Out-Null
    $config = 'C:\\ProgramData\\ssh\\sshd_config'
    ( Get-Content $config ) -replace '^#?PasswordAuthentication .*', 'PasswordAuthentication no' | Set-Content $config
    Restart-Service sshd
    New-NetFirewallRule -Name errand-sshd -DisplayName 'errand sshd' -Profile Any -Direction Inbound `
        -Protocol TCP -LocalPort 22 -Action Allow -ErrorAction SilentlyContinue | Out-Null

    # A machine that lives for minutes has no use for updates, and the
    # scanning of every file a compiler writes halves its speed.
    Step 'quiet'
    Stop-Service wuauserv -ErrorAction SilentlyContinue
    Set-Service wuauserv -StartupType Disabled -ErrorAction SilentlyContinue
    try {{ Set-MpPreference -DisableRealtimeMonitoring $true -ExclusionPath C:\\errand, C:\\BuildTools }} catch {{ }}

    # What copies the project in. Its POSIX permissions would be mapped onto
    # ACLs, and the files it writes come out unreadable to anybody else: off,
    # so that they inherit the ACLs of where they land, as any other file.
    Step 'rsync'
    $bin = '{GUEST_MSYS}\\usr\\bin'
    New-Item -ItemType Directory -Force $bin, '{GUEST_MSYS}\\etc' | Out-Null
    Copy-Item ( Join-Path $media 'rsync\\*' ) $bin
    Set-Content '{GUEST_MSYS}\\etc\\fstab' 'none / cygdrive binary,posix=0,noacl,user 0 0' -Encoding ascii
    & ( Join-Path $bin 'rsync.exe' ) --version | Out-Null
    if ( $LASTEXITCODE ) {{ throw "rsync: exit $LASTEXITCODE" }}
{''.join( steps )}
    Set-Content C:\\errand\\setup.status 'ok'
}} catch {{
    Set-Content C:\\errand\\setup.status "failed: $_"
}} finally {{
    Stop-Transcript
    Stop-Computer -Force
}}
"""


# Windows Server 2025, evaluation edition, English: 180 days without a key, and
# a download Microsoft hands out without asking anything. Index 1 of it is
# Standard, Server Core -- no desktop, which nothing run over ssh needs, and
# which installs and boots in half the time.
EVALUATION_ISO = "https://go.microsoft.com/fwlink/?linkid=2293312&clcid=0x409&culture=en-us&country=us"

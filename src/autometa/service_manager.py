"""Cross-platform installation and lifecycle control for the watch service."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import os
from pathlib import Path
import platform
import shlex
import subprocess
import sys
from typing import Callable, Literal
from xml.sax.saxutils import escape as xml_escape

from autometa.watch_store import RuleStore

BackendName = Literal["systemd", "launchd", "schtasks"]
CommandRunner = Callable[[list[str]], subprocess.CompletedProcess[str]]


class ServiceManagerError(RuntimeError):
    """Raised when a watch-service lifecycle operation cannot complete."""


@dataclass(frozen=True)
class ServiceStatus:
    """Portable report of one installed watch service."""

    backend: BackendName
    name: str
    installed: bool
    running: bool


@dataclass(frozen=True)
class _ServiceSpec:
    """Stable generated-service identity and execution details."""

    backend: BackendName
    name: str
    definition_path: str
    store_path: str
    executable: str
    observer: str


class WatchServiceManager:
    """Install and control a per-user foreground watch-service supervisor."""

    def __init__(
        self,
        store: RuleStore,
        *,
        platform_name: str | None = None,
        home: Path | None = None,
        uid: int | None = None,
        command_runner: CommandRunner | None = None,
    ) -> None:
        """Initialize the service manager with controllable platform dependencies.

        :param store: Rule store owned by the managed watch process.
        :param platform_name: Platform name for backend selection.
        :param home: User home directory for generated service definitions.
        :param uid: Numeric user ID for launchd GUI-domain commands.
        :param command_runner: Injectable command runner for lifecycle operations.
        """
        self.store = store
        self.platform_name = platform_name or platform.system()
        self.home = Path(home) if home is not None else Path.home()
        self.uid = os.getuid() if uid is None and hasattr(os, "getuid") else uid
        self.command_runner = command_runner or self._default_command_runner

    @property
    def manifest_path(self) -> Path:
        """Return the local manifest path for this rule store.

        :return: Manifest located beside the declarative rule store.
        """
        return self.store.path.with_name(f".{self.store.path.name}.service.json")

    def start(self) -> ServiceStatus:
        """Install or update the platform service and start it.

        :return: Status for the started service.
        :raises ServiceManagerError: If no rules exist or a platform command fails.
        """
        if not self.store.load():
            raise ServiceManagerError(
                "Configure at least one watch rule before starting the watch service."
            )
        spec = self._build_spec()
        self._write_definition(spec)
        self._write_manifest(spec)
        if spec.backend == "systemd":
            self._run(["systemctl", "--user", "daemon-reload"])
            self._run(["systemctl", "--user", "enable", "--now", spec.name])
        elif spec.backend == "launchd":
            self._run(
                ["launchctl", "bootout", f"gui/{self._require_uid()}/{spec.name}"],
                (0, 3),
            )
            self._run(
                [
                    "launchctl",
                    "bootstrap",
                    f"gui/{self._require_uid()}",
                    spec.definition_path,
                ]
            )
        else:
            self._run(
                [
                    "schtasks",
                    "/Create",
                    "/TN",
                    spec.name,
                    "/XML",
                    spec.definition_path,
                    "/F",
                ]
            )
            self._run(["schtasks", "/Run", "/TN", spec.name])
        return ServiceStatus(spec.backend, spec.name, installed=True, running=True)

    def stop(self) -> ServiceStatus:
        """Stop the managed service without removing its definition.

        :return: Status showing that the service remains installed but stopped.
        :raises ServiceManagerError: If no managed service exists or stop fails.
        """
        spec = self._load_manifest()
        if spec.backend == "systemd":
            self._run(["systemctl", "--user", "disable", "--now", spec.name])
        elif spec.backend == "launchd":
            self._run(
                ["launchctl", "bootout", f"gui/{self._require_uid()}/{spec.name}"],
                (0, 3),
            )
        else:
            self._run(["schtasks", "/End", "/TN", spec.name], (0, 1))
        return ServiceStatus(spec.backend, spec.name, installed=True, running=False)

    def status(self) -> ServiceStatus:
        """Query the installed service with its persisted backend.

        :return: Installed and running state.
        """
        if not self.manifest_path.is_file():
            spec = self._build_spec()
            return ServiceStatus(
                spec.backend, spec.name, installed=False, running=False
            )
        spec = self._load_manifest()
        if spec.backend == "systemd":
            result = self._run(["systemctl", "--user", "is-active", spec.name], (0, 3))
            running = result.returncode == 0
        elif spec.backend == "launchd":
            result = self._run(
                ["launchctl", "print", f"gui/{self._require_uid()}/{spec.name}"], (0, 3)
            )
            running = result.returncode == 0
        else:
            result = self._run(
                ["schtasks", "/Query", "/TN", spec.name, "/FO", "LIST"], (0, 1)
            )
            running = result.returncode == 0 and "Running" in result.stdout
        return ServiceStatus(spec.backend, spec.name, installed=True, running=running)

    def uninstall(self) -> ServiceStatus:
        """Stop and remove the generated platform service and manifest.

        :return: Status confirming that no managed service remains.
        :raises ServiceManagerError: If no managed service exists or removal fails.
        """
        spec = self._load_manifest()
        if spec.backend == "systemd":
            self._run(["systemctl", "--user", "disable", "--now", spec.name])
            Path(spec.definition_path).unlink(missing_ok=True)
            self._run(["systemctl", "--user", "daemon-reload"])
        elif spec.backend == "launchd":
            self._run(
                ["launchctl", "bootout", f"gui/{self._require_uid()}/{spec.name}"],
                (0, 3),
            )
            Path(spec.definition_path).unlink(missing_ok=True)
        else:
            self._run(["schtasks", "/Delete", "/TN", spec.name, "/F"], (0, 1))
            Path(spec.definition_path).unlink(missing_ok=True)
        self.manifest_path.unlink(missing_ok=True)
        return ServiceStatus(spec.backend, spec.name, installed=False, running=False)

    def _build_spec(self) -> _ServiceSpec:
        """Build the service identity and managed definition path for this platform.

        :return: Definition of the service to generate.
        :raises ServiceManagerError: If the current platform is unsupported.
        """
        digest = hashlib.sha256(str(self.store.path.resolve()).encode()).hexdigest()[
            :12
        ]
        executable = str(Path(sys.executable).resolve())
        if self.platform_name == "Linux":
            name = f"autometa-watch-{digest}"
            path = self.home / ".config" / "systemd" / "user" / f"{name}.service"
            backend: BackendName = "systemd"
        elif self.platform_name == "Darwin":
            name = f"com.autometa.watch.{digest}"
            path = self.home / "Library" / "LaunchAgents" / f"{name}.plist"
            backend = "launchd"
        elif self.platform_name == "Windows":
            name = f"Autometa Watch {digest}"
            path = self.store.path.with_suffix(".task.xml")
            backend = "schtasks"
        else:
            raise ServiceManagerError(
                f"Unsupported platform for managed watch services: {self.platform_name}. "
                "Run 'autometa watch run' under your platform supervisor instead."
            )
        return _ServiceSpec(
            backend,
            name,
            str(path),
            str(self.store.path.resolve()),
            executable,
            "auto",
        )

    def _write_definition(self, spec: _ServiceSpec) -> None:
        """Render and write the platform-specific service definition.

        :param spec: Service definition to render.
        """
        if spec.backend == "systemd":
            path = Path(spec.definition_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(self._render_systemd(spec))
        elif spec.backend == "launchd":
            path = Path(spec.definition_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(self._render_launchd(spec))
        else:
            path = Path(spec.definition_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(self._render_windows_task(spec), encoding="utf-16")

    def _write_manifest(self, spec: _ServiceSpec) -> None:
        """Persist the backend identity used by future lifecycle commands.

        :param spec: Service definition to serialize.
        """
        self.manifest_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.manifest_path.with_suffix(".tmp")
        temporary.write_text(json.dumps(asdict(spec), indent=2, sort_keys=True) + "\n")
        temporary.replace(self.manifest_path)

    def _load_manifest(self) -> _ServiceSpec:
        """Load the persisted service identity.

        :return: Service definition selected when the service was started.
        :raises ServiceManagerError: If no valid managed-service manifest exists.
        """
        if not self.manifest_path.is_file():
            raise ServiceManagerError("No managed autometa watch service is installed.")
        try:
            data = json.loads(self.manifest_path.read_text())
            return _ServiceSpec(**data)
        except (OSError, TypeError, json.JSONDecodeError) as exc:
            raise ServiceManagerError(
                f"Invalid watch-service manifest: {self.manifest_path}"
            ) from exc

    def _render_systemd(self, spec: _ServiceSpec) -> str:
        """Render a systemd user unit.

        :param spec: Service execution definition.
        :return: Complete unit-file content.
        """
        command = shlex.join(
            [
                spec.executable,
                "-m",
                "autometa.cli",
                "watch",
                "run",
                "--observer",
                spec.observer,
            ]
        )
        return (
            "[Unit]\n"
            "Description=Autometa metadata watch service\n\n"
            "[Service]\n"
            "Type=simple\n"
            f"Environment=AUTOMETA_WATCH_STORE={shlex.quote(spec.store_path)}\n"
            f"ExecStart={command}\n"
            "Restart=on-failure\n"
            "RestartSec=5\n\n"
            "[Install]\n"
            "WantedBy=default.target\n"
        )

    def _render_launchd(self, spec: _ServiceSpec) -> str:
        """Render a per-user launchd plist.

        :param spec: Service execution definition.
        :return: Complete plist content.
        """
        arguments = [
            spec.executable,
            "-m",
            "autometa.cli",
            "watch",
            "run",
            "--observer",
            spec.observer,
        ]
        argument_xml = "\n".join(
            f"      <string>{xml_escape(arg)}</string>" for arg in arguments
        )
        return (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" '
            '"http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n'
            '<plist version="1.0">\n<dict>\n'
            f"  <key>Label</key>\n  <string>{xml_escape(spec.name)}</string>\n"
            "  <key>ProgramArguments</key>\n  <array>\n"
            f"{argument_xml}\n  </array>\n"
            "  <key>EnvironmentVariables</key>\n  <dict>\n"
            "    <key>AUTOMETA_WATCH_STORE</key>\n"
            f"    <string>{xml_escape(spec.store_path)}</string>\n"
            "  </dict>\n"
            "  <key>RunAtLoad</key>\n  <true/>\n"
            "  <key>KeepAlive</key>\n  <true/>\n"
            "</dict>\n</plist>\n"
        )

    def _render_windows_task(self, spec: _ServiceSpec) -> str:
        """Render a hidden, per-user Task Scheduler definition.

        :param spec: Service execution definition.
        :return: Complete Task Scheduler XML document.
        """
        return (
            '<?xml version="1.0" encoding="UTF-16"?>\n'
            '<Task version="1.2" '
            'xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">\n'
            "  <RegistrationInfo>\n"
            "    <Description>Autometa metadata watch service</Description>\n"
            "  </RegistrationInfo>\n"
            "  <Triggers>\n"
            "    <LogonTrigger>\n"
            "      <Enabled>true</Enabled>\n"
            "    </LogonTrigger>\n"
            "  </Triggers>\n"
            "  <Principals>\n"
            '    <Principal id="Author">\n'
            "      <LogonType>InteractiveToken</LogonType>\n"
            "      <RunLevel>LeastPrivilege</RunLevel>\n"
            "    </Principal>\n"
            "  </Principals>\n"
            "  <Settings>\n"
            "    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>\n"
            "    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>\n"
            "    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>\n"
            "    <AllowHardTerminate>true</AllowHardTerminate>\n"
            "    <StartWhenAvailable>true</StartWhenAvailable>\n"
            "    <RunOnlyIfIdle>false</RunOnlyIfIdle>\n"
            "    <AllowStartOnDemand>true</AllowStartOnDemand>\n"
            "    <Enabled>true</Enabled>\n"
            "    <Hidden>true</Hidden>\n"
            "    <RunOnlyIfNetworkAvailable>false</RunOnlyIfNetworkAvailable>\n"
            "    <ExecutionTimeLimit>PT0S</ExecutionTimeLimit>\n"
            "    <Priority>7</Priority>\n"
            "  </Settings>\n"
            '  <Actions Context="Author">\n'
            "    <Exec>\n"
            "      <Command>cmd.exe</Command>\n"
            f"      <Arguments>{xml_escape(self._windows_command_arguments(spec))}</Arguments>\n"
            "    </Exec>\n"
            "  </Actions>\n"
            "</Task>\n"
        )

    def _windows_command_arguments(self, spec: _ServiceSpec) -> str:
        """Return Task Scheduler arguments for the watcher command wrapper.

        :param spec: Service execution definition.
        :return: Arguments supplied to ``cmd.exe``.
        """
        command = subprocess.list2cmdline(
            [
                spec.executable,
                "-m",
                "autometa.cli",
                "watch",
                "run",
                "--observer",
                spec.observer,
            ]
        )
        return f'/d /s /c "set "AUTOMETA_WATCH_STORE={spec.store_path}"&&{command}"'

    def _require_uid(self) -> int:
        """Return the launchd GUI-domain user ID.

        :return: Numeric user ID.
        :raises ServiceManagerError: If no user ID is available.
        """
        if self.uid is None:
            raise ServiceManagerError(
                "launchd service management requires a numeric user ID."
            )
        return self.uid

    def _run(
        self, command: list[str], accepted_returncodes: tuple[int, ...] = (0,)
    ) -> subprocess.CompletedProcess[str]:
        """Run a backend command and map unexpected failures to a useful exception.

        :param command: Program and arguments to execute.
        :param accepted_returncodes: Exit statuses that represent expected outcomes.
        :return: Completed command result.
        :raises ServiceManagerError: If the command cannot run or exits unexpectedly.
        """
        try:
            result = self.command_runner(command)
        except OSError as exc:
            raise ServiceManagerError(
                f"Could not run {' '.join(command)}: {exc}"
            ) from exc
        if result.returncode not in accepted_returncodes:
            detail = result.stderr.strip() or result.stdout.strip()
            raise ServiceManagerError(
                f"Service command failed ({result.returncode}): {' '.join(command)}"
                + (f"\n{detail}" if detail else "")
            )
        return result

    @staticmethod
    def _default_command_runner(command: list[str]) -> subprocess.CompletedProcess[str]:
        """Run one service-manager command with captured diagnostics.

        :param command: Program and arguments to execute.
        :return: Completed process result.
        """
        return subprocess.run(command, capture_output=True, text=True, check=False)

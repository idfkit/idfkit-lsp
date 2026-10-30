/**
 * The editor client. It locates and starts each server, declares which documents each one serves,
 * and surfaces server output. It does nothing else, and Constitution Principle V is why: anything
 * that appears here is behaviour that will not exist for a user in a different editor.
 *
 * The one exception is the documentation command, which is recorded in capabilities.json as
 * `editor_specific`. The server resolves the address; opening it is the editor's act, because a
 * server cannot open a browser.
 *
 * Asking an interpreter whether it can run the source server is part of locating that server: the
 * question has to be asked from outside, because a server that cannot load cannot report it. The
 * answer is the exit status of `python -m idfkit_lsp --version`, which any other editor's launch
 * configuration can read in the same way and which the protocol suite holds to.
 */

import * as path from "path";
import * as fs from "fs";
import { execFile } from "child_process";
import * as vscode from "vscode";
import {
    CloseAction,
    ErrorHandler,
    LanguageClient,
    LanguageClientOptions,
    ServerOptions,
    State,
    TransportKind,
} from "vscode-languageclient/node";

/** How the source server is launched. The probe below asks about exactly this command. */
const SOURCE_SERVER_ARGS: readonly string[] = ["-m", "idfkit_lsp"];

/** Generous, because a first run compiles the server's modules. Nothing waits on the probe. */
const PROBE_TIMEOUT_MS = 30_000;

/** A server stopped and started as it stands. The source server is replaced, so it is held below. */
interface ServerHandle {
    readonly id: string;
    readonly client: LanguageClient;
    readonly outputChannel: vscode.OutputChannel;
}

const handles: ServerHandle[] = [];

let source: SourceServer | undefined;

interface DocumentKind {
    readonly language_id: string;
    readonly extensions: readonly string[];
}

interface ServerDeclaration {
    readonly id: string;
    readonly documents: readonly DocumentKind[];
}

interface CapabilityDeclaration {
    readonly servers: readonly ServerDeclaration[];
}

/**
 * Read the capability declaration that ships with the extension.
 *
 * The client never writes down which documents a server serves. Two servers growing toward each
 * other starts with two lists of extensions that disagree, so there is one list and it is the same
 * file both servers advertise from.
 */
function readDeclaration(extensionPath: string): CapabilityDeclaration | undefined {
    const declared = path.join(extensionPath, "capabilities.json");
    try {
        return JSON.parse(fs.readFileSync(declared, "utf8")) as CapabilityDeclaration;
    } catch (err: unknown) {
        // Without the declaration no server has a document selector, so neither one is started.
        // Saying so is the whole difference between an extension that is broken and one that
        // looks installed and answers nothing.
        const msg = err instanceof Error ? err.message : String(err);
        void vscode.window.showErrorMessage(
            `idfkit: ${declared} could not be read (${msg}), so no language server was started.`
        );
        return undefined;
    }
}

interface DocumentSelectorEntry {
    readonly scheme: string;
    readonly language: string;
}

function documentSelector(
    declaration: CapabilityDeclaration | undefined,
    serverId: string
): DocumentSelectorEntry[] {
    const server = declaration?.servers.find((s) => s.id === serverId);
    if (!server) {
        return [];
    }
    return server.documents.map((kind) => ({
        scheme: "file",
        language: kind.language_id,
    }));
}

/**
 * Resolve the Python interpreter that runs the source server.
 *
 * Priority: an explicit setting, then the uv venv beside the server for a development checkout,
 * then whatever `python3` resolves to.
 */
function resolvePythonPath(extensionPath: string): string {
    const configured = vscode.workspace
        .getConfiguration("idfkitLsp")
        .get<string>("pythonPath", "python3")
        .trim();

    // Empty means unset, which is the convention `nodePath` below already uses. Clearing the
    // field in the settings UI leaves an empty string, and a user who cleared it is asking for
    // the default rather than for an empty command. Treating it as a path hands the language
    // client a configuration it rejects, which reports itself as a broken extension instead of
    // as a setting to fix.
    if (configured !== "" && configured !== "python3") {
        if (!path.isAbsolute(configured) && configured.startsWith(".")) {
            const workspaceFolder = vscode.workspace.workspaceFolders?.[0];
            if (workspaceFolder) {
                return path.join(workspaceFolder.uri.fsPath, configured);
            }
        }
        return configured;
    }

    const venvPython = path.join(
        extensionPath,
        "server",
        ".venv",
        process.platform === "win32" ? "Scripts" : "bin",
        process.platform === "win32" ? "python.exe" : "python"
    );
    if (fs.existsSync(venvPython)) {
        return venvPython;
    }

    return configured || "python3";
}

/**
 * Resolve the runtime that runs the model server.
 *
 * The editor already ships one, so a user of this editor needs no separate install: launching
 * `process.execPath` with ELECTRON_RUN_AS_NODE=1 runs it as Node. The override exists for the same
 * reason `pythonPath` does, which is a user whose environment is not the one we guessed.
 */
function resolveNodePath(): { command: string; useElectronNode: boolean } {
    const configured = vscode.workspace
        .getConfiguration("idfkitLsp")
        .get<string>("nodePath", "")
        .trim();
    if (configured) {
        return { command: configured, useElectronNode: false };
    }
    return { command: process.execPath, useElectronNode: true };
}

type SourceServerProbe =
    | { readonly runnable: true; readonly level: string }
    | { readonly runnable: false; readonly reason: string };

/** The last line of what the interpreter wrote, which for a traceback is the line that says why. */
function lastLine(text: string): string | undefined {
    return text
        .split(/\r?\n/)
        .map((line) => line.trim())
        .filter((line) => line !== "")
        .pop();
}

/**
 * Ask an interpreter whether it can run the source server, without starting the server.
 *
 * Only the exit status decides. A release older than the flag ignores it and reads protocol from
 * standard input until end of file, so standard input is closed here: that release exits cleanly
 * with nothing printed, and is correctly reported as able to run.
 */
function probeSourceServer(pythonPath: string, signal: AbortSignal): Promise<SourceServerProbe> {
    const workspaceFolder = vscode.workspace.workspaceFolders?.find(
        (folder) => folder.uri.scheme === "file"
    );
    return new Promise((resolve) => {
        try {
            const child = execFile(
                pythonPath,
                [...SOURCE_SERVER_ARGS, "--version"],
                {
                    // The directory the language client starts the server in, because `python -m`
                    // searches it first and the answer has to hold for that launch.
                    cwd: workspaceFolder?.uri.fsPath,
                    signal,
                    timeout: PROBE_TIMEOUT_MS,
                    windowsHide: true,
                },
                (error, stdout, stderr) => {
                    if (!error) {
                        resolve({ runnable: true, level: stdout.trim() });
                    } else if (error.code === "ENOENT") {
                        resolve({ runnable: false, reason: "the interpreter was not found" });
                    } else if (error.killed) {
                        const seconds = PROBE_TIMEOUT_MS / 1000;
                        resolve({ runnable: false, reason: `no answer within ${seconds} seconds` });
                    } else {
                        resolve({ runnable: false, reason: lastLine(stderr) ?? error.message });
                    }
                }
            );
            child.stdin?.end();
        } catch (err: unknown) {
            // Spawning throws rather than calling back on a command it refuses outright.
            resolve({ runnable: false, reason: err instanceof Error ? err.message : String(err) });
        }
    });
}

/**
 * The language client, without the two defaults that fail badly for a server dying on startup.
 *
 * The library restarts a server that closes during startup, which is the crash loop, and two of its
 * paths on that failure end in an unhandled rejection: an unawaited `stop()` on a client that is not
 * running, and a start promise it no longer holds. A server that closes after it has been running
 * keeps the library's bounded restart.
 */
class SourceClient extends LanguageClient {
    public override createDefaultErrorHandler(maxRestartCount?: number): ErrorHandler {
        const bounded = super.createDefaultErrorHandler(maxRestartCount);
        return {
            error: (error, message, count) => bounded.error(error, message, count),
            closed: async () => {
                if (this.state !== State.Starting) {
                    return bounded.closed();
                }
                // The library forgets the start promise as soon as this answers. Answering after
                // the pending start has failed is what lets that failure reach the caller of
                // `start()`, rather than becoming an unhandled rejection and a false success.
                await new Promise((resolve) => setImmediate(resolve));
                return {
                    action: CloseAction.DoNotRestart,
                    message: "The source server closed during startup and was not restarted.",
                    handled: true,
                };
            },
        };
    }

    public override async stop(timeout?: number): Promise<void> {
        try {
            await super.stop(timeout);
        } catch (err: unknown) {
            const msg = err instanceof Error ? err.message : String(err);
            this.outputChannel.appendLine(`The source server had nothing to stop: ${msg}`);
        }
    }
}

/**
 * The source server: probed before it is started, and replaced rather than restarted, because the
 * interpreter is fixed when a language client is constructed and the setting may have changed.
 */
class SourceServer {
    private client: LanguageClient | undefined;
    private unavailable: string | undefined;
    private pendingNotice: vscode.Disposable | undefined;
    private settled: Promise<void> = Promise.resolve();
    private readonly stopping = new AbortController();

    constructor(
        private readonly context: vscode.ExtensionContext,
        private readonly selector: DocumentSelectorEntry[],
        private readonly outputChannel: vscode.OutputChannel,
        private readonly traceOutputChannel: vscode.OutputChannel
    ) {}

    /** Begin starting the server, without making the caller wait for the interpreter to answer. */
    public start(): void {
        this.settled = this.launch(false);
    }

    /** Replace the server. Someone asked for this, so a failure here is always reported to them. */
    public restart(): Promise<void> {
        this.settled = this.settled.then(async () => {
            await this.client?.stop();
            this.client = undefined;
            await this.launch(true);
        });
        return this.settled;
    }

    /** The running client once any start in progress has settled, or undefined if there is none. */
    public async running(): Promise<LanguageClient | undefined> {
        await this.settled;
        return this.client?.isRunning() ? this.client : undefined;
    }

    public async stop(): Promise<void> {
        this.pendingNotice?.dispose();
        this.stopping.abort();
        await this.settled;
        await this.client?.stop();
    }

    /** State why there is no server. Unprompted this happens once; when asked, it always does. */
    public report(pythonPath: string = resolvePythonPath(this.context.extensionPath)): void {
        const reason = this.unavailable ?? "it is not running";
        void vscode.window
            .showInformationMessage(
                `idfkit: Python source support is off, because "${pythonPath}" cannot run the ` +
                    `source server (${reason}). Model files are not affected.`,
                "Open Settings",
                "Open Output"
            )
            .then((choice) => {
                if (choice === "Open Settings") {
                    void vscode.commands.executeCommand(
                        "workbench.action.openSettings",
                        "idfkitLsp.pythonPath"
                    );
                } else if (choice === "Open Output") {
                    this.outputChannel.show();
                }
            });
    }

    private async launch(asked: boolean): Promise<void> {
        this.pendingNotice?.dispose();
        this.pendingNotice = undefined;
        this.unavailable = undefined;

        const pythonPath = resolvePythonPath(this.context.extensionPath);
        this.outputChannel.appendLine(`Runtime: ${pythonPath}`);
        this.outputChannel.appendLine(`Command: ${pythonPath} ${SOURCE_SERVER_ARGS.join(" ")}`);

        const probe = await probeSourceServer(pythonPath, this.stopping.signal);
        if (this.stopping.signal.aborted) {
            return;
        }
        if (!probe.runnable) {
            this.unavailable = probe.reason;
            this.outputChannel.appendLine(`The source server was not started: ${probe.reason}`);
            if (asked) {
                this.report(pythonPath);
            } else {
                this.noticeOnce(pythonPath);
            }
            return;
        }
        this.outputChannel.appendLine(`Probe: ${probe.level || "able to run, no level reported"}`);

        const serverOptions: ServerOptions = {
            command: pythonPath,
            args: [...SOURCE_SERVER_ARGS],
        };
        const clientOptions: LanguageClientOptions = {
            documentSelector: this.selector,
            outputChannel: this.outputChannel,
            traceOutputChannel: this.traceOutputChannel,
            // Without this the library adds a notification of its own to the one it always shows
            // for a failed start, and that one is the only one this path needs.
            initializationFailedHandler: () => false,
        };
        try {
            this.client = new SourceClient(
                "idfkitLspSource",
                "idfkit source server",
                serverOptions,
                clientOptions
            );
            await this.client.start();
        } catch (err: unknown) {
            this.client = undefined;
            this.unavailable = err instanceof Error ? err.message : String(err);
            this.outputChannel.appendLine(`The source server failed to start: ${this.unavailable}`);
        }
    }

    /**
     * Say so once per interpreter, and not before a document this server serves is open.
     *
     * Nothing here decides whether a project uses the library, because that would be analysis of
     * source in the client. So this is information rather than an error, it is remembered across
     * sessions, and someone who only opens model files never sees it.
     */
    private noticeOnce(pythonPath: string): void {
        const key = `sourceServerNotice:${pythonPath}`;
        if (this.context.globalState.get<boolean>(key)) {
            return;
        }
        const served = (document: vscode.TextDocument): boolean =>
            vscode.languages.match(this.selector, document) > 0;
        const notify = (): void => {
            void this.context.globalState.update(key, true);
            this.report(pythonPath);
        };
        if (vscode.workspace.textDocuments.some(served)) {
            notify();
            return;
        }
        this.pendingNotice = vscode.workspace.onDidOpenTextDocument((document) => {
            if (served(document)) {
                this.pendingNotice?.dispose();
                this.pendingNotice = undefined;
                notify();
            }
        });
    }
}

function createSourceServer(
    context: vscode.ExtensionContext,
    declaration: CapabilityDeclaration | undefined
): SourceServer | undefined {
    const selector = documentSelector(declaration, "source");
    if (selector.length === 0) {
        return undefined;
    }

    const outputChannel = vscode.window.createOutputChannel("idfkit: source server");
    const traceOutputChannel = vscode.window.createOutputChannel(
        "idfkit: source server (trace)"
    );
    // Both channels are handed to the extension host here, so a reactivation does not leave a
    // second pair behind.
    context.subscriptions.push(outputChannel, traceOutputChannel);

    return new SourceServer(context, selector, outputChannel, traceOutputChannel);
}

function startModelServer(
    context: vscode.ExtensionContext,
    declaration: CapabilityDeclaration | undefined
): ServerHandle | undefined {
    const selector = documentSelector(declaration, "model");
    if (selector.length === 0) {
        return undefined;
    }

    const outputChannel = vscode.window.createOutputChannel("idfkit: model server");
    const traceOutputChannel = vscode.window.createOutputChannel(
        "idfkit: model server (trace)"
    );
    // Both channels are handed to the extension host here, so an early return below still
    // disposes of them and a reactivation does not leave a second pair behind.
    context.subscriptions.push(outputChannel, traceOutputChannel);

    const bundle = path.join(context.extensionPath, "model-server", "dist", "main.js");
    if (!fs.existsSync(bundle)) {
        outputChannel.appendLine(
            `[ERROR] model server bundle not found at ${bundle}. Model files will not be served.`
        );
        return undefined;
    }

    const { command, useElectronNode } = resolveNodePath();
    outputChannel.appendLine(`Runtime: ${command}`);
    outputChannel.appendLine(`Command: ${command} ${bundle}`);

    const env = { ...process.env };
    if (useElectronNode) {
        env.ELECTRON_RUN_AS_NODE = "1";
    }

    const serverOptions: ServerOptions = {
        run: {
            command,
            args: [bundle, "--stdio"],
            transport: TransportKind.stdio,
            options: { env },
        },
        debug: {
            command,
            args: [bundle, "--stdio"],
            transport: TransportKind.stdio,
            options: { env },
        },
    };

    const clientOptions: LanguageClientOptions = {
        documentSelector: selector,
        outputChannel,
        traceOutputChannel,
    };

    const client = new LanguageClient(
        "idfkitLspModel",
        "idfkit model server",
        serverOptions,
        clientOptions
    );

    client.start().catch((err: unknown) => {
        const msg = err instanceof Error ? err.message : String(err);
        outputChannel.appendLine(`[ERROR] model server failed to start: ${msg}`);
        outputChannel.show(true);
    });

    return { id: "model", client, outputChannel };
}

export function activate(context: vscode.ExtensionContext): void {
    const declaration = readDeclaration(context.extensionPath);

    source = createSourceServer(context, declaration);
    source?.start();

    const model = startModelServer(context, declaration);
    if (model) {
        handles.push(model);
    }

    context.subscriptions.push(
        vscode.commands.registerCommand("idfkitLsp.restartServer", async () => {
            // One server failing to come back must not leave the other stopped, so each restart
            // is reported where that server's output already is and the loop carries on.
            for (const handle of handles) {
                try {
                    await handle.client.stop();
                } catch {
                    // The client may be in a starting or start-failed state.
                }
                try {
                    await handle.client.start();
                } catch (err: unknown) {
                    const msg = err instanceof Error ? err.message : String(err);
                    handle.outputChannel.appendLine(
                        `[ERROR] ${handle.id} server failed to restart: ${msg}`
                    );
                    void vscode.window.showErrorMessage(
                        `The idfkit ${handle.id} server failed to restart: ${msg}`
                    );
                }
            }
            await source?.restart();
        })
    );

    // Recorded in capabilities.json as editor_specific: the server resolves the address and
    // opening it is the editor's act. Nothing about the answer is decided here.
    context.subscriptions.push(
        vscode.commands.registerCommand("idfkitLsp.openDocumentation", async () => {
            if (!source) {
                return;
            }
            const client = await source.running();
            if (!client) {
                source.report();
                return;
            }
            const objectType = await vscode.window.showInputBox({
                prompt: "EnergyPlus object type",
                placeHolder: "e.g. Zone, Material, BuildingSurface:Detailed",
            });
            if (!objectType) {
                return;
            }
            try {
                const url = await client.sendRequest<string | null>(
                    "workspace/executeCommand",
                    {
                        command: "idfkit.openDocumentation",
                        arguments: [objectType],
                    }
                );
                if (url) {
                    await vscode.env.openExternal(vscode.Uri.parse(url));
                } else {
                    void vscode.window.showWarningMessage(
                        `No documentation found for "${objectType}".`
                    );
                }
            } catch (err: unknown) {
                const msg = err instanceof Error ? err.message : String(err);
                void vscode.window.showErrorMessage(`Failed to open documentation: ${msg}`);
            }
        })
    );
}

export function deactivate(): Thenable<void> | undefined {
    const stopping = handles.map((handle) => handle.client.stop().catch(() => undefined));
    handles.length = 0;
    if (source) {
        stopping.push(source.stop());
        source = undefined;
    }
    return Promise.all(stopping).then(() => undefined);
}

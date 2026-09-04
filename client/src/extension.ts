/**
 * The editor client. It locates and starts each server, declares which documents each one serves,
 * and surfaces server output. It does nothing else, and Constitution Principle V is why: anything
 * that appears here is behaviour that will not exist for a user in a different editor.
 *
 * The one exception is the documentation command, which is recorded in capabilities.json as
 * `editor_specific`. The server resolves the address; opening it is the editor's act, because a
 * server cannot open a browser.
 */

import * as path from "path";
import * as fs from "fs";
import * as vscode from "vscode";
import {
    LanguageClient,
    LanguageClientOptions,
    ServerOptions,
    TransportKind,
} from "vscode-languageclient/node";

/** One entry per server. Which documents each serves comes from capabilities.json, read below. */
interface ServerHandle {
    readonly id: string;
    readonly client: LanguageClient;
    readonly outputChannel: vscode.OutputChannel;
}

const handles: ServerHandle[] = [];

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
    } catch {
        return undefined;
    }
}

function documentSelector(
    declaration: CapabilityDeclaration | undefined,
    serverId: string
): { scheme: string; language: string }[] {
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
        .get<string>("pythonPath", "python3");

    if (configured !== "python3") {
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

    return configured;
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
        .get<string>("nodePath", "");
    if (configured) {
        return { command: configured, useElectronNode: false };
    }
    return { command: process.execPath, useElectronNode: true };
}

function startSourceServer(
    context: vscode.ExtensionContext,
    declaration: CapabilityDeclaration | undefined
): ServerHandle | undefined {
    const selector = documentSelector(declaration, "source");
    if (selector.length === 0) {
        return undefined;
    }

    const outputChannel = vscode.window.createOutputChannel("idfkit: source server");
    const traceOutputChannel = vscode.window.createOutputChannel(
        "idfkit: source server (trace)"
    );

    const pythonPath = resolvePythonPath(context.extensionPath);
    outputChannel.appendLine(`Runtime: ${pythonPath}`);
    outputChannel.appendLine(`Command: ${pythonPath} -m idfkit_lsp`);

    const serverOptions: ServerOptions = {
        command: pythonPath,
        args: ["-m", "idfkit_lsp"],
    };

    const clientOptions: LanguageClientOptions = {
        documentSelector: selector,
        outputChannel,
        traceOutputChannel,
    };

    const client = new LanguageClient(
        "idfkitLspSource",
        "idfkit source server",
        serverOptions,
        clientOptions
    );

    client.start().catch((err: unknown) => {
        const msg = err instanceof Error ? err.message : String(err);
        outputChannel.appendLine(`[ERROR] source server failed to start: ${msg}`);
        void vscode.window
            .showErrorMessage(
                `The idfkit source server failed to start. Is idfkit-lsp installed for "${pythonPath}"?`,
                "Open Output",
                "Open Settings"
            )
            .then((choice) => {
                if (choice === "Open Output") {
                    outputChannel.show();
                } else if (choice === "Open Settings") {
                    void vscode.commands.executeCommand(
                        "workbench.action.openSettings",
                        "idfkitLsp.pythonPath"
                    );
                }
            });
    });

    return { id: "source", client, outputChannel };
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

    for (const handle of [
        startSourceServer(context, declaration),
        startModelServer(context, declaration),
    ]) {
        if (handle) {
            handles.push(handle);
            context.subscriptions.push(handle.outputChannel);
        }
    }

    context.subscriptions.push(
        vscode.commands.registerCommand("idfkitLsp.restartServer", async () => {
            for (const handle of handles) {
                try {
                    await handle.client.stop();
                } catch {
                    // The client may be in a starting or start-failed state.
                }
                await handle.client.start();
            }
        })
    );

    // Recorded in capabilities.json as editor_specific: the server resolves the address and
    // opening it is the editor's act. Nothing about the answer is decided here.
    context.subscriptions.push(
        vscode.commands.registerCommand("idfkitLsp.openDocumentation", async () => {
            const source = handles.find((handle) => handle.id === "source");
            if (!source) {
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
                const url = await source.client.sendRequest<string | null>(
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
    return Promise.all(stopping).then(() => undefined);
}

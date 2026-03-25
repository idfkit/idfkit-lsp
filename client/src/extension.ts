import * as path from "path";
import * as fs from "fs";
import * as vscode from "vscode";
import {
    LanguageClient,
    LanguageClientOptions,
    ServerOptions,
} from "vscode-languageclient/node";

let client: LanguageClient | undefined;

/**
 * Resolve the Python interpreter to use for the language server.
 *
 * Priority:
 * 1. Explicit user setting (idfkitLsp.pythonPath) if changed from default
 * 2. The venv inside server/.venv relative to the extension root (development)
 * 3. Fall back to "python3"
 */
function resolvePythonPath(extensionPath: string): string {
    const config = vscode.workspace.getConfiguration("idfkitLsp");
    const configured = config.get<string>("pythonPath", "python3");

    // If user explicitly configured a non-default path, resolve it
    if (configured !== "python3") {
        // Resolve workspace-relative paths (e.g., "./venv/bin/python")
        if (!path.isAbsolute(configured) && configured.startsWith(".")) {
            const workspaceFolder = vscode.workspace.workspaceFolders?.[0];
            if (workspaceFolder) {
                return path.join(workspaceFolder.uri.fsPath, configured);
            }
        }
        return configured;
    }

    // In development, look for the uv venv bundled with the server
    const venvPython = path.join(
        extensionPath,
        "server",
        ".venv",
        "bin",
        "python"
    );
    if (fs.existsSync(venvPython)) {
        return venvPython;
    }

    return configured;
}

export function activate(context: vscode.ExtensionContext): void {
    const outputChannel = vscode.window.createOutputChannel(
        "idfkit Language Server"
    );
    const traceOutputChannel = vscode.window.createOutputChannel(
        "idfkit Language Server (Trace)"
    );

    outputChannel.appendLine("Activating idfkit Language Server extension...");
    outputChannel.appendLine(`Extension path: ${context.extensionPath}`);

    const pythonPath = resolvePythonPath(context.extensionPath);
    outputChannel.appendLine(`Resolved Python: ${pythonPath}`);

    const serverOptions: ServerOptions = {
        command: pythonPath,
        args: ["-m", "idfkit_lsp"],
    };
    outputChannel.appendLine(
        `Server command: ${pythonPath} -m idfkit_lsp`
    );

    const clientOptions: LanguageClientOptions = {
        documentSelector: [{ scheme: "file", language: "python" }],
        outputChannel,
        traceOutputChannel,
    };

    client = new LanguageClient(
        "idfkitLsp",
        "idfkit Language Server",
        serverOptions,
        clientOptions
    );

    outputChannel.appendLine("Starting language client...");
    client.start().then(
        () => {
            outputChannel.appendLine("Language client started successfully.");
        },
        (err: unknown) => {
            const msg = err instanceof Error ? err.message : String(err);
            outputChannel.appendLine(`[ERROR] Server failed to start: ${msg}`);
            if (err instanceof Error && err.stack) {
                outputChannel.appendLine(err.stack);
            }
            vscode.window
                .showErrorMessage(
                    `idfkit Language Server failed to start. ` +
                        `Is idfkit-lsp installed for "${pythonPath}"? ` +
                        `Run: pip install -e ./server`,
                    "Open Output",
                    "Open Settings"
                )
                .then((choice) => {
                    if (choice === "Open Output") {
                        outputChannel.show();
                    } else if (choice === "Open Settings") {
                        vscode.commands.executeCommand(
                            "workbench.action.openSettings",
                            "idfkitLsp.pythonPath"
                        );
                    }
                });
        }
    );

    context.subscriptions.push(
        vscode.commands.registerCommand(
            "idfkitLsp.restartServer",
            async () => {
                if (client) {
                    try {
                        await client.stop();
                    } catch {
                        // Client may be in starting/startFailed state
                    }
                    await client.start();
                }
            }
        )
    );

    context.subscriptions.push(
        vscode.commands.registerCommand(
            "idfkitLsp.openDocumentation",
            async () => {
                const objectType = await vscode.window.showInputBox({
                    prompt: "EnergyPlus object type",
                    placeHolder: "e.g. Zone, Material, BuildingSurface:Detailed",
                });
                if (!objectType || !client) return;
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
                        vscode.window.showWarningMessage(
                            `No documentation found for "${objectType}".`
                        );
                    }
                } catch (err: unknown) {
                    const msg =
                        err instanceof Error ? err.message : String(err);
                    vscode.window.showErrorMessage(
                        `Failed to open documentation: ${msg}`
                    );
                }
            }
        )
    );
}

export function deactivate(): Thenable<void> | undefined {
    if (client) {
        return client.stop().catch(() => undefined);
    }
    return undefined;
}

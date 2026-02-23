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

    // If user explicitly configured a non-default path, use it as-is
    if (configured !== "python3") {
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
    const pythonPath = resolvePythonPath(context.extensionPath);

    const outputChannel = vscode.window.createOutputChannel(
        "idfkit Language Server"
    );
    const traceOutputChannel = vscode.window.createOutputChannel(
        "idfkit Language Server (Trace)"
    );

    outputChannel.appendLine(`Using Python: ${pythonPath}`);

    const serverOptions: ServerOptions = {
        command: pythonPath,
        args: ["-m", "idfkit_lsp"],
    };

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

    client.start().catch((err: unknown) => {
        const msg = err instanceof Error ? err.message : String(err);
        outputChannel.appendLine(`[ERROR] Server failed to start: ${msg}`);
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
    });

    context.subscriptions.push(
        vscode.commands.registerCommand(
            "idfkitLsp.restartServer",
            async () => {
                if (client) {
                    await client.stop();
                    await client.start();
                }
            }
        )
    );
}

export function deactivate(): Thenable<void> | undefined {
    if (client) {
        return client.stop();
    }
    return undefined;
}

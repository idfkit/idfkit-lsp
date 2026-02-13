import * as vscode from "vscode";
import {
    LanguageClient,
    LanguageClientOptions,
    ServerOptions,
} from "vscode-languageclient/node";

let client: LanguageClient | undefined;

export function activate(context: vscode.ExtensionContext): void {
    const config = vscode.workspace.getConfiguration("idfkitLsp");
    const pythonPath = config.get<string>("pythonPath", "python3");

    const serverOptions: ServerOptions = {
        command: pythonPath,
        args: ["-m", "idfkit_lsp"],
    };

    const clientOptions: LanguageClientOptions = {
        documentSelector: [{ scheme: "file", language: "python" }],
        outputChannel: vscode.window.createOutputChannel(
            "idfkit Language Server"
        ),
    };

    client = new LanguageClient(
        "idfkitLsp",
        "idfkit Language Server",
        serverOptions,
        clientOptions
    );

    client.start();

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

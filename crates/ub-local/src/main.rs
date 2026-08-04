mod api;
mod config;
mod orchestrate;
mod pipeline;
mod rag;

use crate::api::{app, AppState};
use crate::api::jobs::JobStore;
use crate::config::settings;
use crate::orchestrate::parse_document;
use crate::pipeline::{ensure_output_subdir, export_knowledge_bundle, upload_bundle};
use clap::{Parser, Subcommand};
use std::path::PathBuf;
use tracing_subscriber::EnvFilter;

#[derive(Parser, Debug)]
#[command(name = "ub-local", about = "userbank-local CLI (Rust)")]
struct Cli {
    #[command(subcommand)]
    command: Commands,
}

#[derive(Subcommand, Debug)]
enum Commands {
    /// Start local control plane
    Serve {
        #[arg(long)]
        host: Option<String>,
        #[arg(long)]
        port: Option<u16>,
    },
    /// Parse document to corpus JSON
    Parse {
        input: PathBuf,
        #[arg(long)]
        out: Option<PathBuf>,
        #[arg(long, default_value_t = false)]
        skip_mineru: bool,
    },
    /// Export knowledge bundle (flatten + embed via rag)
    Export {
        #[arg(long)]
        corpus: PathBuf,
        #[arg(long)]
        output_dir: PathBuf,
        #[arg(long, default_value = "local-doc")]
        document_id: String,
        #[arg(long)]
        filename: Option<String>,
        #[arg(long)]
        org: Option<String>,
    },
    /// Upload bundle to userbank-api import-vectors
    Upload {
        #[arg(long)]
        bundle_dir: PathBuf,
        #[arg(long, default_value = "auto")]
        mode: String,
        #[arg(long)]
        org: Option<String>,
        #[arg(long)]
        api: Option<String>,
    },
}

#[tokio::main]
async fn main() -> anyhow::Result<()> {
    tracing_subscriber::fmt()
        .with_env_filter(EnvFilter::try_from_default_env().unwrap_or_else(|_| "info".into()))
        .init();

    let cli = Cli::parse();
    match cli.command {
        Commands::Serve { host, port } => {
            let s = settings();
            let host = host.unwrap_or_else(|| s.ub_local_host.clone());
            let port = port.unwrap_or(s.ub_local_port);
            let state = AppState {
                jobs: JobStore::new(),
            };
            let addr = format!("{host}:{port}");
            let listener = tokio::net::TcpListener::bind(&addr).await?;
            tracing::info!("ub-local listening on http://{addr}");
            axum::serve(listener, app(state)).await?;
        }
        Commands::Parse {
            input,
            out,
            skip_mineru,
        } => {
            let work = out.unwrap_or_else(|| ensure_output_subdir("cli-parse"));
            let corpus = parse_document(&input, &work, skip_mineru)?;
            println!("{}", corpus.display());
        }
        Commands::Export {
            corpus,
            output_dir,
            document_id,
            filename,
            org,
        } => {
            let result = export_knowledge_bundle(
                &corpus,
                &output_dir,
                &document_id,
                filename.as_deref(),
                org.as_deref(),
                None,
            )
            .await?;
            println!("{}", result["output_dir"].as_str().unwrap_or(""));
        }
        Commands::Upload {
            bundle_dir,
            mode,
            org,
            api,
        } => {
            let result = upload_bundle(&bundle_dir, &mode, org.as_deref(), api.as_deref()).await?;
            println!(
                "upload complete mode={}",
                result["mode"].as_str().unwrap_or("?")
            );
        }
    }
    Ok(())
}

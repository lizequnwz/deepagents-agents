import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Activity,
  ArrowRight,
  BarChart3,
  BookOpen,
  Check,
  ChevronDown,
  Database,
  Download,
  Ellipsis,
  FileText,
  History,
  LayoutDashboard,
  Menu,
  MessageSquare,
  Moon,
  Plus,
  Search,
  Send,
  ShieldCheck,
  Sun,
  Trash2,
  X,
} from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { api, post, message } from "./api";
import {
  ChartFigure,
  DatasetPreview,
  Empty,
  Loading,
  Notice,
} from "./components";
import { Attachment, DocumentViewer, SchemaReview } from "./Intake";
import DashboardPanel from "./DashboardPanel";
import { RunReview } from "./RunReview";
import { VoiceInput } from "./VoiceInput";
import type {
  Answer,
  Conversation,
  ConversationSummary,
  Dashboard,
  DashboardRevision,
  Dataset,
  DocumentRef,
  Run,
  Source,
  Upload,
} from "./types";

type Tab = "dashboard" | "report" | "data";
const ACTIVE = [
  "queued",
  "running",
  "approval_required",
  "clarification_required",
  "stopping",
];
const PHASES: Record<string, string> = {
  understanding: "Understanding the question",
  retrieving: "Retrieving data",
  retrieving_data: "Retrieving data",
  analyzing: "Analyzing the evidence",
  findings_ready: "Findings ready",
  reporting: "Preparing report",
  preparing_report: "Preparing report",
  completed: "Complete",
};
function initialParam(name: string) {
  return new URLSearchParams(location.search).get(name);
}

export default function App() {
  const [threadId, setThreadId] = useState<string | null>(() =>
    initialParam("thread"),
  );
  const [dashboardId, setDashboardId] = useState<string | null>(() =>
    initialParam("dashboard"),
  );
  const [history, setHistory] = useState<ConversationSummary[]>([]);
  const [sources, setSources] = useState<Source[]>([]);
  const [source, setSource] = useState("");
  const [health, setHealth] = useState<{
    status: string;
    model: string;
    api_contract_version: number;
    errors: string[];
    sql_approval_required: boolean;
    python_approval_required: boolean;
  } | null>(null);
  const [conversation, setConversation] = useState<Conversation | null>(null);
  const [run, setRun] = useState<Run | null>(null);
  const [tracking, setTracking] = useState<string | null>(null);
  const [datasets, setDatasets] = useState<Dataset[]>([]);
  const [uploads, setUploads] = useState<Upload[]>([]);
  const [documents, setDocuments] = useState<DocumentRef[]>([]);
  const [dashboards, setDashboards] = useState<DashboardRevision[]>([]);
  const [dashboard, setDashboard] = useState<Dashboard | null>(null);
  const [selectedRun, setSelectedRun] = useState<string | null>(null);
  const [selectedDataset, setSelectedDataset] = useState("");
  const [selectedDocument, setSelectedDocument] = useState("");
  const [tab, setTab] = useState<Tab>("dashboard");
  const [draft, setDraft] = useState("");
  const [workspaceSearch, setWorkspaceSearch] = useState("");
  const [mobileView, setMobileView] = useState<"canvas" | "conversation">("canvas");
  const [error, setError] = useState("");
  const [acknowledgement, setAcknowledgement] = useState("");
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(false);
  const [sidebar, setSidebar] = useState(false);
  const [showChat, setShowChat] = useState(true);
  const [deleteDialog, setDeleteDialog] = useState(false);
  const [pollVersion, setPollVersion] = useState(0);
  const [theme, setTheme] = useState(
    () => localStorage.getItem("analytics-theme") ?? "light",
  );
  const chatEnd = useRef<HTMLDivElement>(null);
  const navigation = useRef<HTMLElement>(null);
  const initialViewThread = useRef<string | null>(null);
  const loadGeneration = useRef(0);
  const newRuns = useRef(new Set<string>());
  const selection = useRef({ threadId, dashboardId });
  selection.current = { threadId, dashboardId };
  const active = !!run && ACTIVE.includes(run.status);
  const awaitingDashboard =
    !!dashboardId && dashboard?.revision.dashboard_id !== dashboardId;
  const unreviewed = uploads.find((u) => !u.confirmed);
  const currentTurn =
    conversation?.turns.find((t) => t.run_id === selectedRun) ??
    conversation?.turns.at(-1);
  const answer: Answer | null =
    currentTurn?.answer ?? (!dashboard && run?.findings ? run.findings : null);
  const sourceInfo = sources.find(
    (s) => s.source_id === conversation?.source_id,
  );
  const sourceName =
    sourceInfo?.name ??
    (conversation?.source_id.startsWith("upload:")
      ? "Reviewed file workspace"
      : conversation?.source_id.startsWith("documents:")
        ? "Document workspace"
        : (conversation?.source_id ?? "Select your data"));
  const filteredHistory = useMemo(
    () => history.filter((item) =>
      item.title.toLocaleLowerCase().includes(workspaceSearch.trim().toLocaleLowerCase()),
    ),
    [history, workspaceSearch],
  );

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    localStorage.setItem("analytics-theme", theme);
  }, [theme]);
  useEffect(() => {
    const narrow = window.matchMedia("(max-width: 1080px)");
    const resize = () => {
      if (!narrow.matches) setSidebar(false);
    };
    narrow.addEventListener("change", resize);
    return () => narrow.removeEventListener("change", resize);
  }, []);
  useEffect(() => {
    if (!sidebar) return;
    const previous = document.activeElement as HTMLElement | null;
    const drawer = navigation.current;
    const overflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    drawer?.querySelector<HTMLButtonElement>('[aria-label="Close navigation"]')?.focus();
    const keydown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        setSidebar(false);
      }
      if (event.key !== "Tab" || !drawer) return;
      const controls = [...drawer.querySelectorAll<HTMLElement>("button:not(:disabled),input:not(:disabled),a[href]")]
        .filter((control) => control.getClientRects().length > 0);
      const first = controls[0], last = controls.at(-1);
      if (event.shiftKey && (document.activeElement === first || !drawer.contains(document.activeElement))) {
        event.preventDefault();
        last?.focus();
      } else if (!event.shiftKey && (document.activeElement === last || !drawer.contains(document.activeElement))) {
        event.preventDefault();
        first?.focus();
      }
    };
    document.addEventListener("keydown", keydown);
    return () => {
      document.body.style.overflow = overflow;
      document.removeEventListener("keydown", keydown);
      previous?.focus();
    };
  }, [sidebar]);
  useEffect(() => {
    let current: HTMLElement | null = null;
    let previous: HTMLElement | null = null;
    const focusable = (dialog: HTMLElement) =>
      [
        ...dialog.querySelectorAll<HTMLElement>(
          "button:not(:disabled),a[href],input:not(:disabled),select:not(:disabled),textarea:not(:disabled)",
        ),
      ].filter((element) => element.getClientRects().length > 0);
    const observer = new MutationObserver(() => {
      const dialog = document.querySelector<HTMLElement>(
        ".modal-backdrop .modal",
      );
      if (dialog === current) return;
      if (dialog) {
        previous = document.activeElement as HTMLElement;
        current = dialog;
        focusable(dialog)[0]?.focus();
      } else {
        current = null;
        previous?.focus();
        previous = null;
      }
    });
    observer.observe(document.body, { childList: true, subtree: true });
    const keydown = (event: KeyboardEvent) => {
      if (!current) return;
      if (event.key === "Escape") {
        const close =
          current.querySelector<HTMLButtonElement>(
            'button[aria-label^="Cancel"],button[aria-label^="Close"]',
          ) ??
          [...current.querySelectorAll("button")].find(
            (button) => button.textContent?.trim() === "Cancel",
          );
        if (close && !close.disabled) {
          event.preventDefault();
          close.click();
        }
      }
      if (event.key === "Tab") {
        const controls = focusable(current);
        if (!controls.length) return;
        const first = controls[0],
          last = controls.at(-1)!;
        if (
          event.shiftKey &&
          (document.activeElement === first ||
            !current.contains(document.activeElement))
        ) {
          event.preventDefault();
          last.focus();
        } else if (
          !event.shiftKey &&
          (document.activeElement === last ||
            !current.contains(document.activeElement))
        ) {
          event.preventDefault();
          first.focus();
        }
      }
    };
    document.addEventListener("keydown", keydown);
    return () => {
      observer.disconnect();
      document.removeEventListener("keydown", keydown);
    };
  }, []);
  const refreshHistory = useCallback(async () => {
    const items = await api<ConversationSummary[]>("/api/conversations");
    setHistory(items);
  }, []);
  useEffect(() => {
    let ignore = false;
    Promise.all([
      api<typeof health>("/health"),
      api<{ sources: Source[]; default_source_id: string | null }>(
        "/api/data-sources",
      ),
      api<ConversationSummary[]>("/api/conversations"),
    ])
      .then(([health, sources, history]) => {
        if (ignore) return;
        setHealth(health);
        setSources(sources.sources);
        setSource(
          sources.default_source_id ??
            sources.sources.find((s) => s.ready)?.source_id ??
            "",
        );
        setHistory(history);
      })
      .catch((e) => {
        if (!ignore) setError(message(e));
      });
    return () => {
      ignore = true;
    };
  }, []);
  function navigate(thread: string | null, dashboard: string | null = null) {
    setThreadId(thread);
    setDashboardId(dashboard);
    setSidebar(false);
    setError("");
    const params = new URLSearchParams();
    if (thread) params.set("thread", thread);
    if (dashboard) params.set("dashboard", dashboard);
    window.history.pushState(
      {},
      "",
      `${location.pathname}${params.size ? "?" + params : ""}`,
    );
  }
  useEffect(() => {
    const pop = () => {
      setThreadId(initialParam("thread"));
      setDashboardId(initialParam("dashboard"));
    };
    addEventListener("popstate", pop);
    return () => removeEventListener("popstate", pop);
  }, []);
  const refreshThread = useCallback(async () => {
    if (!threadId) return;
    const generation = loadGeneration.current;
    const [conversation, data, uploads, documents, dashboards] =
      await Promise.all([
        api<Conversation>(`/api/conversations/${threadId}`),
        api<{ datasets: Dataset[] }>(`/api/conversations/${threadId}/datasets`),
        api<{ uploads: Upload[] }>(`/api/conversations/${threadId}/uploads`),
        api<{ documents: DocumentRef[] }>(
          `/api/conversations/${threadId}/documents`,
        ),
        api<{ dashboards: DashboardRevision[] }>(
          `/api/conversations/${threadId}/dashboards`,
        ),
      ]);
    if (
      generation !== loadGeneration.current ||
      selection.current.threadId !== threadId
    )
      return;
    setConversation(conversation);
    if (initialViewThread.current !== threadId) {
      initialViewThread.current = threadId;
      setMobileView(uploads.uploads.some((upload) => !upload.confirmed) || conversation.turns.at(-1)?.answer.report ? "canvas" : "conversation");
    }
    setDatasets(data.datasets);
    setUploads(uploads.uploads);
    setDocuments(documents.documents);
    setDashboards(dashboards.dashboards);
    setSelectedDataset((previous) =>
      data.datasets.some((d) => d.result_id === previous)
        ? previous
        : (data.datasets[0]?.result_id ?? ""),
    );
    setSelectedDocument((previous) =>
      documents.documents.some((d) => d.document_id === previous)
        ? previous
        : (documents.documents[0]?.document_id ?? ""),
    );
    setSelectedRun((previous) =>
      conversation.turns.some((t) => t.run_id === previous)
        ? previous
        : (conversation.turns.at(-1)?.run_id ?? null),
    );
    if (conversation.active_run_id) {
      newRuns.current.add(conversation.active_run_id);
      setTracking(conversation.active_run_id);
    } else if (conversation.run_ids.length)
      setTracking(conversation.run_ids.at(-1)!);
    return dashboards.dashboards;
  }, [threadId, tracking]);
  useEffect(() => {
    const generation = ++loadGeneration.current;
    initialViewThread.current = null;
    setDraft("");
    setAcknowledgement("");
    setConversation(null);
    setRun(null);
    setTracking(null);
    setDashboard(null);
    setDatasets([]);
    setUploads([]);
    setDocuments([]);
    setDashboards([]);
    setSelectedRun(null);
    if (!threadId) {
      setLoading(false);
      return;
    }
    setLoading(true);
    void refreshThread()
      .catch((e) => {
        if (generation === loadGeneration.current) setError(message(e));
      })
      .finally(() => {
        if (generation === loadGeneration.current) setLoading(false);
      });
  }, [threadId]);
  const refreshDashboard = useCallback(async () => {
    if (!threadId || !dashboardId) return;
    const result = await api<Dashboard>(
      `/api/conversations/${threadId}/dashboards/${dashboardId}`,
    );
    if (
      selection.current.threadId === threadId &&
      selection.current.dashboardId === dashboardId
    )
      setDashboard(result);
  }, [threadId, dashboardId]);
  useEffect(() => {
    setDashboard(null);
    if (threadId && dashboardId)
      void refreshDashboard().catch((e) => setError(message(e)));
  }, [threadId, dashboardId]);
  useEffect(() => {
    if (!tracking || !threadId) return;
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout>;
    async function poll() {
      try {
        const next = await api<Run>(`/api/runs/${tracking}`);
        if (cancelled) return;
        setRun(next);
        if (ACTIVE.includes(next.status)) timer = setTimeout(poll, 1000);
        else {
          const refreshedDashboards = await refreshThread();
          if (cancelled) return;
          await refreshHistory();
          if (cancelled) return;
          if (dashboardId) await refreshDashboard();
          if (cancelled) return;
          if (next.status === "completed") {
            setSelectedRun(tracking);
            if (newRuns.current.has(next.run_id)) {
              newRuns.current.delete(next.run_id);
              const created = refreshedDashboards?.find(
                (item) => item.run_id === tracking,
              );
              if (created && created.dashboard_id !== dashboardId) {
                setDashboardId(created.dashboard_id);
                setTab("dashboard");
                setMobileView("canvas");
                const params = new URLSearchParams({
                  thread: next.thread_id,
                  dashboard: created.dashboard_id,
                });
                window.history.replaceState(
                  {},
                  "",
                  `${location.pathname}?${params}`,
                );
              }
            }
          }
        }
      } catch (e) {
        if (!cancelled) {
          setError(message(e));
          timer = setTimeout(poll, 3000);
        }
      }
    }
    void poll();
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [tracking, threadId, dashboardId, pollVersion]);
  useEffect(() => {
    if (chatEnd.current?.getClientRects().length)
      chatEnd.current.scrollIntoView({ block: "nearest", behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "instant" : "smooth" });
  }, [conversation?.turns.length, run?.status]);
  const onSaved = (result: Dashboard) => {
    if (selection.current.threadId !== threadId) return;
    setDashboard(result);
    const revision = result.revision;
    setDashboardId(revision.dashboard_id);
    setDashboards((items) => [
      revision,
      ...items.filter((d) => d.dashboard_id !== revision.dashboard_id),
    ]);
    const params = new URLSearchParams({
      thread: threadId!,
      dashboard: revision.dashboard_id,
    });
    window.history.replaceState({}, "", `${location.pathname}?${params}`);
  };
  async function create() {
    if (!source) return;
    const generation = loadGeneration.current;
    setBusy(true);
    setError("");
    try {
      const result = await post<{ thread_id: string }>("/api/conversations", {
        source_id: source,
      });
      if (generation !== loadGeneration.current) return;
      navigate(result.thread_id);
      await refreshHistory();
    } catch (e) {
      setError(message(e));
    } finally {
      setBusy(false);
    }
  }
  async function submit(createDashboard = false) {
    if (!draft.trim() || !threadId || awaitingDashboard) return;
    const submittingThread = threadId;
    setBusy(true);
    setError("");
    setAcknowledgement("");
    try {
      if (active) {
        const correction = await post<{ message: string }>(
          `/api/runs/${run!.run_id}/corrections`,
          {
            message: draft.trim(),
          },
        );
        if (selection.current.threadId !== submittingThread) return;
        setAcknowledgement(correction.message);
        setDraft("");
      } else {
        const result = await post<{ run_id: string }>(
          `/api/conversations/${threadId}/messages`,
          {
            message: draft.trim(),
            dashboard: createDashboard,
            ...(dashboard
              ? {
                  dashboard_id: dashboard.revision.dashboard_id,
                  dashboard_revision: dashboard.revision.revision_id,
                }
              : {}),
          },
        );
        if (selection.current.threadId !== submittingThread) return;
        newRuns.current.add(result.run_id);
        setTracking(result.run_id);
        setRun(null);
        setDraft("");
        await refreshThread();
      }
    } catch (e) {
      setError(message(e));
    } finally {
      setBusy(false);
    }
  }
  async function remove() {
    if (!threadId) return;
    const deletingThread = threadId;
    setBusy(true);
    try {
      await api(`/api/conversations/${threadId}`, { method: "DELETE" });
      if (selection.current.threadId !== deletingThread) return;
      setDeleteDialog(false);
      navigate(null);
      await refreshHistory();
    } catch (e) {
      setError(message(e));
    } finally {
      setBusy(false);
    }
  }
  function attached(thread: string) {
    if (selection.current.threadId !== threadId) return;
    if (thread === threadId) {
      void refreshThread().catch((e) => setError(message(e)));
    } else navigate(thread);
    void refreshHistory();
    setTab("data");
    setMobileView("canvas");
  }
  const needsReview =
    run?.status === "approval_required" ||
    run?.status === "clarification_required";
  const cannotSubmit = busy || !draft.trim() || !!unreviewed || needsReview || awaitingDashboard;
  const events = run?.events ?? currentTurn?.activities ?? [];
  const reportId = dashboard?.revision.report_id ?? answer?.report?.report_id;
  const displayRunId =
    dashboard?.revision.run_id ??
    currentTurn?.run_id ??
    (run?.findings ? run.run_id : null);
  const displayTitle =
    dashboard?.revision.spec.title ??
    answer?.report?.title ??
    currentTurn?.user_message ??
    "Analytics workspace";
  const visibleTurns = useMemo(() => conversation?.turns ?? [], [conversation]);

  if (health && health.api_contract_version !== 23)
    return (
      <main className="welcome">
        <h1>Restart the local services</h1>
        <Notice error>
          The workspace expects API contract 23. The API reports{" "}
          {health.api_contract_version ?? "no contract version"}. Stop the
          services and restart them together before continuing.
        </Notice>
        <button onClick={() => location.reload()}>Reload workspace</button>
      </main>
    );
  return (
    <>
      <a className="skip-link" href="#workspace-main">
        Skip to workspace
      </a>
      <div className={`app-shell ${sidebar ? "sidebar-open" : ""}`}>
        <aside className="sidebar" ref={navigation} role={sidebar ? "dialog" : undefined} aria-modal={sidebar || undefined} aria-label="Workspace navigation">
          <div className="brand">
            <div className="brand-mark">
              <BarChart3 size={23} />
            </div>
            <div>
              <strong>Analytics</strong>
              <span>WORKSPACE</span>
            </div>
            <button
              className="mobile-only icon-button"
              aria-label="Close navigation"
              onClick={() => setSidebar(false)}
            >
              <X size={19} />
            </button>
          </div>
          <button className="new-workspace" onClick={() => navigate(null)}>
            <Plus size={18} />
            New workspace
          </button>
          <label className="workspace-search">
            <span className="sr-only">Search workspaces</span>
            <Search size={16} aria-hidden="true" />
            <input type="search" aria-label="Search workspaces" placeholder="Find a workspace" value={workspaceSearch} onChange={(event) => setWorkspaceSearch(event.target.value)} />
          </label>
          <div className="sidebar-heading">
            <History size={14} />
            Saved workspaces
          </div>
          <nav aria-label="Saved workspaces">
            {history.length === 0 ? (
              <p className="sidebar-empty">
                Your conversations and dashboards will be saved here.
              </p>
            ) : filteredHistory.length === 0 ? (
              <div className="sidebar-empty">
                <p>No matching workspaces.</p>
                <button onClick={() => setWorkspaceSearch("")}>Clear search</button>
              </div>
            ) : (
              filteredHistory.map((item) => (
                <button
                  className={`history-item ${item.thread_id === threadId ? "active" : ""}`}
                  key={item.thread_id}
                  aria-current={item.thread_id === threadId ? "page" : undefined}
                  title={item.title}
                  onClick={() => navigate(item.thread_id)}
                >
                  <MessageSquare size={15} />
                  <span>{item.title}</span>
                  {item.active_run_id && (
                    <span className="status-dot" aria-label="Active analysis" />
                  )}
                </button>
              ))
            )}
          </nav>
          <div className="sidebar-bottom">
            <div className="local-label">
              <ShieldCheck size={16} />
              <span>Local analytical workspace</span>
            </div>
            <div className="sidebar-footer">
              <button
                className="icon-button"
                aria-label={
                  theme === "light" ? "Use dark theme" : "Use light theme"
                }
                onClick={() => setTheme(theme === "light" ? "dark" : "light")}
              >
                {theme === "light" ? <Moon size={17} /> : <Sun size={17} />}
              </button>
              <span>
                {health?.status === "ok"
                  ? "Application ready"
                  : health
                    ? "Check configuration"
                    : "Connecting…"}
              </span>
            </div>
          </div>
        </aside>
        {sidebar && (
          <button
            className="nav-scrim"
            aria-label="Close navigation"
            onClick={() => setSidebar(false)}
          />
        )}
        <div className="workspace" inert={sidebar}>
          <header className="app-header">
            <div className="header-title">
              <button
                className="mobile-only icon-button"
                aria-label="Open navigation"
                onClick={() => setSidebar(true)}
              >
                <Menu size={20} />
              </button>
              <div>
                <p className="eyebrow header-breadcrumb">
                  {threadId ? "Workspace" : "Analytics workspace"}
                </p>
                <h1>{threadId ? sourceName : "Analytics workspace"}</h1>
              </div>
            </div>
            <div className="header-actions">
              {threadId && (
                <>
                  <span className="source-chip" title={`Source: ${sourceName}`}>
                    <Database size={13} />
                    {conversation?.source_id.startsWith("upload:")
                      ? "Files"
                      : conversation?.source_id.startsWith("documents:")
                        ? "Documents"
                        : "Connected source"}
                  </span>
                  <button
                    className={`conversation-toggle ${showChat ? "selected" : ""}`}
                    aria-label="Toggle conversation"
                    aria-pressed={showChat}
                    onClick={() => setShowChat(!showChat)}
                  >
                    <MessageSquare size={18} />
                    <span>Conversation</span>
                  </button>
                  <details className="workspace-overflow" onKeyDown={(event) => {
                    if (event.key === "Escape") {
                      event.currentTarget.open = false;
                      event.currentTarget.querySelector("summary")?.focus();
                    }
                  }}>
                    <summary aria-label="Workspace options"><Ellipsis size={20} aria-hidden="true" /></summary>
                    <div className="workspace-menu">
                      <p>Workspace actions</p>
                      <button className="danger-text" aria-label="Delete workspace" disabled={active} onClick={(event) => {
                        const menu = event.currentTarget.closest("details");
                        if (menu) {
                          menu.open = false;
                          menu.querySelector("summary")?.focus();
                        }
                        setDeleteDialog(true);
                      }}><Trash2 size={17} aria-hidden="true" />Delete workspace</button>
                    </div>
                  </details>
                </>
              )}
            </div>
          </header>
          {error && (
            <div className="global-error">
              <Notice error>{error}</Notice>
              <button
                className="icon-button"
                aria-label="Dismiss error"
                onClick={() => setError("")}
              >
                <X size={16} />
              </button>
            </div>
          )}
          {!threadId ? (
            <main id="workspace-main" className="welcome">
              <div className="welcome-intro">
                <p className="eyebrow">Questions. Findings. Decisions.</p>
                <h2>Start with your data.</h2>
                <p>
                  Choose a source or review a file. Ask your question, then keep
                  the findings, dashboards and reports together.
                </p>
              </div>
              <div className="start-options">
                <section className="start-card">
                  <Database size={24} />
                  <h3>Connect to your data</h3>
                  <p>
                    Use a configured source and its reviewed business
                    definitions.
                  </p>
                  <label>
                    Source
                    <select
                      aria-label="Source"
                      value={source}
                      onChange={(e) => setSource(e.target.value)}
                    >
                      <option value="">Choose a source</option>
                      {sources.map((s) => (
                        <option
                          key={s.source_id}
                          value={s.source_id}
                          disabled={!s.ready}
                        >
                          {s.name}
                          {!s.ready ? " · unavailable" : ""}
                        </option>
                      ))}
                    </select>
                  </label>
                  {sources.find((s) => s.source_id === source)?.description && (
                    <p className="small muted">
                      {sources.find((s) => s.source_id === source)?.description}
                    </p>
                  )}
                  <button
                    className="primary"
                    disabled={busy || !source}
                    onClick={() => void create()}
                  >
                    {busy ? "Opening…" : "Open workspace"}
                    <ArrowRight size={16} />
                  </button>
                </section>
                <section className="start-card">
                  <FileText size={24} />
                  <h3>Bring your own files</h3>
                  <p>
                    Import a table, or attach documents for cited context.
                    Review table types before analysis.
                  </p>
                  <div className="file-formats">
                    <span>CSV</span>
                    <span>Parquet</span>
                    <span>Excel</span>
                    <span>PDF / text</span>
                  </div>
                  <Attachment onComplete={attached} onError={setError} />
                  <p className="small muted">
                    One file workspace can contain several explicitly reviewed
                    tables.
                  </p>
                </section>
              </div>
              {health && health.errors.length > 0 && (
                <Notice>{health.errors.join(" ")}</Notice>
              )}
              <div className="welcome-footnote">
                <ShieldCheck size={16} />
                Answers, charts and reports retain their saved evidence.
              </div>
            </main>
          ) : loading ? (
            <main id="workspace-main">
              <Loading label="Opening saved workspace…" />
            </main>
          ) : (
            <>
              <div className="mobile-view-switch" role="group" aria-label="Workspace panels">
                <button aria-pressed={mobileView === "canvas"} onClick={() => setMobileView("canvas")}><LayoutDashboard size={17} aria-hidden="true" />Findings</button>
                <button aria-pressed={mobileView === "conversation"} onClick={() => { setMobileView("conversation"); setShowChat(true); }}><MessageSquare size={17} aria-hidden="true" />Conversation{active && <span className="mobile-work-status">{run?.status === "approval_required" ? "Review" : run?.status === "clarification_required" ? "Reply needed" : "Working"}</span>}</button>
              </div>
              <main id="workspace-main" tabIndex={-1} className={`work-area ${showChat ? "" : "chat-hidden"} mobile-${mobileView}`}>
              <section className="canvas" aria-label="Findings">
                <div className="canvas-nav">
                  <div
                    className="tabs"
                    role="tablist"
                    aria-label="Workspace view"
                    onKeyDown={(event) => {
                      const tabs: Tab[] = ["dashboard", "report", "data"];
                      const current = tabs.indexOf(tab);
                      let next = current;
                      if (event.key === "ArrowRight") next = (current + 1) % tabs.length;
                      else if (event.key === "ArrowLeft") next = (current + tabs.length - 1) % tabs.length;
                      else if (event.key === "Home") next = 0;
                      else if (event.key === "End") next = tabs.length - 1;
                      else return;
                      event.preventDefault();
                      setTab(tabs[next]);
                      document.getElementById(`tab-${tabs[next]}`)?.focus();
                    }}
                  >
                    {(
                      [
                        {
                          key: "dashboard",
                          label: dashboardId ? "Dashboard" : "Findings",
                          icon: LayoutDashboard,
                        },
                        { key: "report", label: "Report", icon: BookOpen },
                        { key: "data", label: "Data", icon: Database },
                      ] as const
                    ).map(({ key, label, icon: Icon }) => (
                      <button
                        key={key}
                        role="tab"
                        id={`tab-${key}`}
                        aria-controls={`panel-${key}`}
                        aria-selected={tab === key}
                        tabIndex={tab === key ? 0 : -1}
                        className={tab === key ? "active" : ""}
                        onClick={() => setTab(key)}
                      >
                        <Icon size={16} />
                        {label}
                      </button>
                    ))}
                  </div>
                  {dashboards.length > 0 && (
                    <label className="saved-view-select">
                      <span className="sr-only">Saved dashboard</span>
                      <select
                        aria-label="Saved dashboard"
                        value={dashboardId ?? ""}
                        onChange={(e) => {
                          setDashboardId(e.target.value || null);
                          const params = new URLSearchParams({
                            thread: threadId,
                          });
                          if (e.target.value)
                            params.set("dashboard", e.target.value);
                          window.history.replaceState(
                            {},
                            "",
                            `${location.pathname}?${params}`,
                          );
                        }}
                      >
                        <option value="">Latest findings</option>
                        {dashboards.map((d) => (
                          <option value={d.dashboard_id} key={d.dashboard_id}>
                            {d.spec.title} · v{d.version}
                          </option>
                        ))}
                      </select>
                      <ChevronDown size={14} />
                    </label>
                  )}
                </div>
                {unreviewed ? (
                  <SchemaReview
                    upload={unreviewed}
                    onConfirmed={() =>
                      void refreshThread().catch((e) => setError(message(e)))
                    }
                  />
                ) : (
                  <>
                    <div
                      role="tabpanel"
                      id="panel-dashboard"
                      aria-labelledby="tab-dashboard"
                      hidden={tab !== "dashboard"}
                    >
                      {tab === "dashboard" && (
                        <DashboardPanel
                          key={`${threadId}:${dashboardId ?? "results"}`}
                          threadId={threadId}
                          dashboard={dashboard}
                          answer={answer}
                          runId={currentTurn?.run_id ?? null}
                          busy={active}
                          onSaved={onSaved}
                          onRun={(id) => {
                            if (selection.current.threadId !== threadId) return;
                            newRuns.current.add(id);
                            setTracking(id);
                            setRun(null);
                            setPollVersion((v) => v + 1);
                          }}
                          onReload={() =>
                            void refreshDashboard().catch((e) =>
                              setError(message(e)),
                            )
                          }
                        />
                      )}
                    </div>
                    <div
                      role="tabpanel"
                      id="panel-report"
                      aria-labelledby="tab-report"
                      hidden={tab !== "report"}
                    >
                      {tab === "report" &&
                        (reportId ? (
                          <>
                            <div className="canvas-heading">
                              <div>
                                <p className="eyebrow">
                                  Evidence-backed publication
                                </p>
                                <h2>{displayTitle}</h2>
                              </div>
                              <div className="button-group">
                                <a
                                  className="button secondary"
                                  href={`/api/reports/${reportId}/download`}
                                >
                                  <Download size={15} />
                                  HTML report
                                </a>
                                {displayRunId && (
                                  <a
                                    className="button secondary"
                                    href={`/api/runs/${displayRunId}/download?report_id=${reportId}`}
                                  >
                                    Data and calculations
                                  </a>
                                )}
                              </div>
                            </div>
                            <iframe
                              title="Published HTML report"
                              className="report-frame"
                              src={`/api/reports/${reportId}/view`}
                              sandbox="allow-scripts allow-downloads"
                            />
                          </>
                        ) : (
                          <Empty
                            title="Every supported answer has a report"
                            icon={BookOpen}
                          >
                            The report will appear after evidence is selected
                            and published. You can return to it later.
                          </Empty>
                        ))}
                    </div>
                    <div
                      role="tabpanel"
                      id="panel-data"
                      aria-labelledby="tab-data"
                      hidden={tab !== "data"}
                    >
                      {tab === "data" && (
                        <div className="data-panel">
                          <div className="canvas-heading">
                            <div>
                              <p className="eyebrow">Inspect your evidence</p>
                              <h2>Data and context</h2>
                              <p className="muted">
                                Saved snapshots retain their scope and
                                provenance.
                              </p>
                            </div>
                            <Attachment
                              threadId={threadId}
                              disabled={active}
                              onComplete={attached}
                              onError={setError}
                            />
                          </div>
                          {datasets.length > 0 ? (
                            <>
                              <label>
                                Saved dataset
                                <select
                                  aria-label="Saved dataset"
                                  value={selectedDataset}
                                  onChange={(e) =>
                                    setSelectedDataset(e.target.value)
                                  }
                                >
                                  {datasets.map((d) => (
                                    <option
                                      key={d.result_id}
                                      value={d.result_id}
                                    >
                                      {d.label} · {d.row_count.toLocaleString()}{" "}
                                      rows
                                    </option>
                                  ))}
                                </select>
                              </label>
                              {selectedDataset && (
                                <DatasetPreview
                                  key={selectedDataset}
                                  resultId={selectedDataset}
                                />
                              )}
                            </>
                          ) : (
                            <Empty title="No saved table yet">
                              Attach a table or ask a question to obtain
                              evidence from your selected source.
                            </Empty>
                          )}
                          {documents.length > 0 && (
                            <section className="documents-panel">
                              <label>
                                Context document
                                <select
                                  value={selectedDocument}
                                  onChange={(e) =>
                                    setSelectedDocument(e.target.value)
                                  }
                                >
                                  {documents.map((d) => (
                                    <option
                                      key={d.document_id}
                                      value={d.document_id}
                                    >
                                      {d.filename}
                                    </option>
                                  ))}
                                </select>
                              </label>
                              {documents.find(
                                (d) => d.document_id === selectedDocument,
                              ) && (
                                <DocumentViewer
                                  key={selectedDocument}
                                  threadId={threadId}
                                  document={documents.find(
                                    (d) => d.document_id === selectedDocument,
                                  )!}
                                  onImport={() =>
                                    void refreshThread().catch((e) =>
                                      setError(message(e)),
                                    )
                                  }
                                />
                              )}
                            </section>
                          )}
                        </div>
                      )}
                    </div>
                  </>
                )}
              </section>
                <aside className="conversation-panel" aria-label="Conversation">
                  <div className="conversation-header">
                    <div>
                      <MessageSquare size={16} />
                      <h2>Conversation</h2>
                    </div>
                    <span className="small muted conversation-context">
                      Ask, refine and investigate
                    </span>
                  </div>
                  <div className="conversation-messages">
                    {visibleTurns.length === 0 && !run && (
                      <div className="chat-intro">
                        <div className="assistant-avatar">
                          <BarChart3 size={20} />
                        </div>
                        <h3>What would you like to understand?</h3>
                        <p>
                          Ask a question, investigate a change, or describe a
                          dashboard.
                        </p>
                        {sourceInfo?.examples.slice(0, 3).map((example) => (
                          <button
                            className="example-question"
                            key={example.label}
                            onClick={() => setDraft(example.question)}
                          >
                            {example.label}
                            <ArrowRight size={14} />
                          </button>
                        ))}
                      </div>
                    )}
                    {visibleTurns.map((turn) => (
                      <article className="chat-turn" key={turn.run_id}>
                        <div className="user-message">{turn.user_message}</div>
                        <div className="assistant-message">
                          <div className="assistant-label">
                            <BarChart3 size={14} />
                            Analytics
                          </div>
                          <div className="markdown">
                            <ReactMarkdown remarkPlugins={[remarkGfm]}>
                              {turn.answer.answer}
                            </ReactMarkdown>
                          </div>
                          {turn.answer.partial && (
                            <Notice>
                              Partial findings. Some questions remain
                              unresolved.
                            </Notice>
                          )}
                          {turn.answer.assumptions.length > 0 && (
                            <details>
                              <summary>Assumptions and limits</summary>
                              <ul>
                                {turn.answer.assumptions.map((a, i) => (
                                  <li key={i}>{a}</li>
                                ))}
                              </ul>
                              {turn.answer.unresolved_questions.map((q, i) => (
                                <p key={i}>{q}</p>
                              ))}
                            </details>
                          )}
                          {turn.answer.report && (
                            <button
                              className="result-link"
                              onClick={() => {
                                setSelectedRun(turn.run_id);
                                setDashboardId(null);
                                setTab("report");
                                setMobileView("canvas");
                              }}
                            >
                              <BookOpen size={14} />
                              View report
                            </button>
                          )}
                        </div>
                      </article>
                    ))}
                    {run &&
                      !visibleTurns.some((t) => t.run_id === run.run_id) && (
                        <article className="chat-turn">
                          <div className="user-message">{run.question}</div>
                          {run.findings && (
                            <div className="assistant-message markdown">
                              <ReactMarkdown remarkPlugins={[remarkGfm]}>
                                {run.findings.answer}
                              </ReactMarkdown>
                            </div>
                          )}
                        </article>
                      )}
                    {run && (
                      <div className="run-state">
                        <div
                          className="run-status"
                          role="status"
                          aria-live="polite"
                        >
                          {active ? (
                            <span className="status-dot pulse" />
                          ) : (
                            <Check size={15} />
                          )}
                          <span>
                            {run.status === "approval_required"
                              ? "Review required"
                              : run.status === "clarification_required"
                                ? "Clarification needed"
                                : run.status === "paused"
                                  ? "Paused"
                                  : run.status === "failed"
                                    ? "Needs attention"
                                    : run.status === "completed"
                                      ? "Complete"
                                      : (PHASES[run.phase] ??
                                        run.phase.replaceAll("_", " "))}
                          </span>
                        </div>
                        <RunReview
                          key={`${run.run_id}-${run.status}`}
                          run={run}
                          onUpdate={() => {
                            if (selection.current.threadId !== threadId) return;
                            setTracking(run.run_id);
                            setPollVersion((v) => v + 1);
                          }}
                        />
                      </div>
                    )}
                    {events.length > 0 && (
                      <details className="activity-panel">
                        <summary>
                          <Activity size={14} />
                          Activity · {events.length} events
                        </summary>
                        <ol>
                          {events.map((event) => (
                            <li key={event.id}>
                              <span className={`event-mark ${event.phase}`} />
                              <div>
                                {event.label}
                                {event.tool && (
                                  <details>
                                    <summary>Calculation details</summary>
                                    <pre>
                                      {JSON.stringify(event.tool, null, 2)}
                                    </pre>
                                  </details>
                                )}
                              </div>
                            </li>
                          ))}
                        </ol>
                      </details>
                    )}
                    <div ref={chatEnd} />
                  </div>
                  <form
                    className="composer"
                    onSubmit={(e) => {
                      e.preventDefault();
                      void submit();
                    }}
                  >
                    <label className="composer-label" htmlFor="message">
                      Message
                    </label>
                    <textarea
                      id="message"
                      aria-label="Message"
                      placeholder={
                        unreviewed
                          ? "Confirm the table schema to continue."
                          : active
                            ? "Add a correction to this analysis…"
                            : "Ask a question or describe a dashboard…"
                      }
                      value={draft}
                      onChange={(e) => setDraft(e.target.value)}
                      disabled={!!unreviewed || needsReview}
                      maxLength={20000}
                      onKeyDown={(e) => {
                        if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
                          e.preventDefault();
                          void submit();
                        }
                      }}
                    />
                    <div className="composer-actions">
                      <div className="composer-tools">
                      <Attachment
                        threadId={threadId}
                        disabled={active || !!unreviewed}
                        onComplete={attached}
                        onError={setError}
                      />
                      <VoiceInput
                        key={threadId}
                        disabled={active || !!unreviewed || busy}
                        onDraft={(text) =>
                          setDraft((previous) =>
                            previous ? previous + " " + text : text,
                          )
                        }
                        onError={setError}
                      />
                      </div>
                      <div className="composer-submit-actions">
                      {!active && <button className="create-dashboard-button" type="button" disabled={cannotSubmit} onClick={() => void submit(true)} title="Create a saved dashboard from this question"><LayoutDashboard size={16} aria-hidden="true" /><span>Create dashboard</span></button>}
                      <button
                        className="primary send-button"
                        type="submit"
                        aria-label={active ? "Send correction" : "Send"}
                        disabled={cannotSubmit}
                      >
                        <Send size={16} />
                        <span>{active ? "Correct" : "Send"}</span>
                      </button>
                      </div>
                    </div>
                    {acknowledgement && (
                      <p
                        className="composer-acknowledgement small"
                        role="status"
                      >
                        {acknowledgement}
                      </p>
                    )}
                    <p className="small muted composer-hint">
                      {active
                        ? "Corrections apply at the next safe step."
                        : "Send a question, or create a dashboard from this request."}
                    </p>
                  </form>
                </aside>
              </main>
            </>
          )}
        </div>
      </div>
      {deleteDialog && (
        <div className="modal-backdrop">
          <section
            className="modal"
            role="dialog"
            aria-modal="true"
            aria-labelledby="delete-title"
          >
            <h2 id="delete-title">Delete this workspace?</h2>
            <p>
              This removes its conversation, datasets, dashboards and reports.
            </p>
            <div className="form-actions">
              <button onClick={() => setDeleteDialog(false)}>Cancel</button>
              <button
                className="danger-button"
                disabled={busy}
                onClick={() => void remove()}
              >
                Delete workspace permanently
              </button>
            </div>
          </section>
        </div>
      )}
    </>
  );
}

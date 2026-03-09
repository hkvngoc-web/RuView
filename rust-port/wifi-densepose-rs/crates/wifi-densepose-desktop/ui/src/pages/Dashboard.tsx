import React, { useEffect, useState, useRef } from "react";
import { StatusBadge } from "../components/StatusBadge";
import type { HealthStatus } from "../types";

interface DiscoveredNode {
  ip: string;
  mac: string | null;
  hostname: string | null;
  node_id: number;
  firmware_version: string | null;
  health: HealthStatus;
  last_seen: string;
}

interface ServerStatus {
  running: boolean;
  pid: number | null;
  http_port: number | null;
  ws_port: number | null;
}

const Dashboard: React.FC = () => {
  const [nodes, setNodes] = useState<DiscoveredNode[]>([]);
  const [serverStatus, setServerStatus] = useState<ServerStatus | null>(null);
  const [scanning, setScanning] = useState(false);

  const handleScan = async () => {
    setScanning(true);
    try {
      const { invoke } = await import("@tauri-apps/api/core");
      const found = await invoke<DiscoveredNode[]>("discover_nodes", { timeoutMs: 3000 });
      setNodes(found);
    } catch (err) {
      console.error("Discovery failed:", err);
    } finally {
      setScanning(false);
    }
  };

  const fetchServerStatus = async () => {
    try {
      const { invoke } = await import("@tauri-apps/api/core");
      const status = await invoke<ServerStatus>("server_status");
      setServerStatus(status);
    } catch (err) {
      console.error("Server status check failed:", err);
    }
  };

  useEffect(() => {
    handleScan();
    fetchServerStatus();
  }, []);

  const onlineCount = nodes.filter((n) => n.health === "online").length;

  return (
    <div style={{ padding: "var(--space-5)", maxWidth: 1100 }}>
      {/* Header */}
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          marginBottom: "var(--space-5)",
        }}
      >
        <div>
          <h2 className="heading-lg" style={{ margin: 0 }}>Bảng Điều Khiển</h2>
          <p style={{ fontSize: 13, color: "var(--text-secondary)", marginTop: 2 }}>
            Tổng quan hệ thống và thao tác nhanh
          </p>
        </div>
        <button
          onClick={handleScan}
          disabled={scanning}
          className="btn-gradient"
          style={{ opacity: scanning ? 0.6 : 1 }}
        >
          {scanning ? "Đang quét..." : "Quét Mạng"}
        </button>
      </div>

      {/* Hàng thống kê */}
      <div
        className="stagger-children"
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(4, 1fr)",
          gap: "var(--space-4)",
          marginBottom: "var(--space-5)",
        }}
      >
        <StatCard label="Tổng Số Nút" value={nodes.length} />
        <StatCard label="Trực tuyến" value={onlineCount} color="var(--status-online)" />
        <StatCard label="Ngoại tuyến" value={nodes.length - onlineCount} color={nodes.length - onlineCount > 0 ? "var(--status-error)" : "var(--text-muted)"} />
        <StatCard
          label="Máy chủ"
          value={serverStatus?.running ? "Đang chạy" : "Đã dừng"}
          color={serverStatus?.running ? "var(--status-online)" : "var(--status-error)"}
          isText
        />
      </div>

      {/* Bố cục hai cột */}
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "var(--space-4)", marginBottom: "var(--space-5)" }}>
        {/* Bảng máy chủ */}
        <div className="card">
          <h3 className="heading-sm" style={{ marginBottom: "var(--space-3)" }}>Máy Chủ Cảm Biến</h3>
          <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
            <span
              className={`status-dot ${serverStatus?.running ? "status-dot--online" : "status-dot--error"}`}
              style={{ width: 10, height: 10 }}
            />
            <span style={{ fontSize: 14, color: "var(--text-primary)", fontWeight: 500 }}>
              {serverStatus?.running ? "Đang chạy" : "Đã dừng"}
            </span>
            {serverStatus?.running && serverStatus.pid && (
              <span className="data" style={{ marginLeft: "auto" }}>
                PID {serverStatus.pid}
              </span>
            )}
          </div>
          {serverStatus?.running && serverStatus.http_port && (
            <div style={{ marginTop: "var(--space-3)", display: "flex", gap: "var(--space-4)" }}>
              <PortTag label="HTTP" port={serverStatus.http_port} />
              {serverStatus.ws_port && <PortTag label="WS" port={serverStatus.ws_port} />}
            </div>
          )}
        </div>

        {/* Bảng thao tác nhanh */}
        <div className="card">
          <h3 className="heading-sm" style={{ marginBottom: "var(--space-3)" }}>Thao Tác Nhanh</h3>
          <div style={{ display: "flex", flexDirection: "column", gap: "var(--space-2)" }}>
            <QuickAction label="Nạp Firmware" desc="Nạp qua cổng nối tiếp" />
            <QuickAction label="Đẩy Cập Nhật OTA" desc="Cập nhật không dây tới các nút" />
            <QuickAction label="Tải Lên WASM" desc="Triển khai module biên" />
          </div>
        </div>
      </div>

      {/* Danh sách nút */}
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "var(--space-3)" }}>
        <h3 className="heading-sm">Các Nút Đã Phát Hiện ({nodes.length})</h3>
      </div>

      {nodes.length === 0 ? (
        <div className="card empty-state">
          <div className="empty-state-icon">{"\u25C9"}</div>
          <div style={{ fontSize: 14, fontWeight: 600, color: "var(--text-secondary)" }}>
            Chưa phát hiện nút nào
          </div>
          <div style={{ fontSize: 13, color: "var(--text-muted)", maxWidth: 280, textAlign: "center", lineHeight: 1.5 }}>
            Click "Quét Mạng" to discover ESP32 devices on your local network.
          </div>
        </div>
      ) : (
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fill, minmax(300px, 1fr))",
            gap: "var(--space-4)",
          }}
        >
          {nodes.map((node, i) => (
            <NodeDashCard key={node.mac || i} node={node} />
          ))}
        </div>
      )}
    </div>
  );
};

function useCountUp(target: number, duration = 600): number {
  const [current, setCurrent] = useState(0);
  const prevTarget = useRef(0);
  useEffect(() => {
    const start = prevTarget.current;
    prevTarget.current = target;
    if (target === start) return;
    const startTime = performance.now();
    const tick = (now: number) => {
      const elapsed = now - startTime;
      const progress = Math.min(elapsed / duration, 1);
      const eased = 1 - Math.pow(1 - progress, 3); // ease-out cubic
      setCurrent(Math.round(start + (target - start) * eased));
      if (progress < 1) requestAnimationFrame(tick);
    };
    requestAnimationFrame(tick);
  }, [target, duration]);
  return current;
}

function StatCard({
  label,
  value,
  color,
  isText = false,
}: {
  label: string;
  value: number | string;
  color?: string;
  isText?: boolean;
}) {
  const animatedValue = useCountUp(typeof value === "number" ? value : 0);
  const displayValue = isText || typeof value === "string" ? value : animatedValue;

  return (
    <div
      className="card-glow"
      style={{ padding: "var(--space-4)" }}
    >
      <div
        style={{
          fontSize: 10,
          textTransform: "uppercase",
          letterSpacing: "0.06em",
          color: "var(--text-muted)",
          marginBottom: "var(--space-2)",
          fontWeight: 600,
        }}
      >
        {label}
      </div>
      <div
        style={{
          fontFamily: "var(--font-mono)",
          fontSize: isText ? 16 : 28,
          fontWeight: 600,
          color: color || "var(--text-primary)",
          letterSpacing: "-0.02em",
          lineHeight: 1.1,
        }}
      >
        {displayValue}
      </div>
    </div>
  );
}

function PortTag({ label, port }: { label: string; port: number }) {
  return (
    <span
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 6,
        padding: "4px 10px",
        background: "var(--bg-base)",
        borderRadius: "var(--radius-full)",
        fontSize: 11,
      }}
    >
      <span style={{ color: "var(--text-muted)", fontWeight: 600 }}>{label}</span>
      <span className="mono" style={{ color: "var(--text-secondary)" }}>:{port}</span>
    </span>
  );
}

function QuickAction({ label, desc }: { label: string; desc: string }) {
  return (
    <div
      style={{
        display: "flex",
        justifyContent: "space-between",
        alignItems: "center",
        padding: "10px 12px",
        background: "var(--bg-base)",
        borderRadius: "var(--radius-md)",
        cursor: "pointer",
        transition: "background 0.1s ease",
      }}
      onMouseEnter={(e) => (e.currentTarget.style.background = "var(--bg-hover)")}
      onMouseLeave={(e) => (e.currentTarget.style.background = "var(--bg-base)")}
    >
      <div>
        <div style={{ fontSize: 13, fontWeight: 500, color: "var(--text-primary)" }}>{label}</div>
        <div style={{ fontSize: 11, color: "var(--text-muted)" }}>{desc}</div>
      </div>
      <span style={{ color: "var(--text-muted)", fontSize: 14 }}>{"\u203A"}</span>
    </div>
  );
}

function NodeDashCard({ node }: { node: DiscoveredNode }) {
  return (
    <div
      className="card"
      style={{
        padding: "var(--space-4)",
        cursor: "pointer",
        opacity: node.health === "online" ? 1 : 0.6,
      }}
    >
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "start", marginBottom: "var(--space-3)" }}>
        <div>
          <div style={{ fontWeight: 600, fontSize: 14, marginBottom: 1 }}>
            {node.hostname || `Node ${node.node_id}`}
          </div>
          <div className="mono" style={{ fontSize: 12, color: "var(--text-muted)" }}>
            {node.ip}
          </div>
        </div>
        <StatusBadge status={node.health} />
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "6px 16px", fontSize: 12 }}>
        <KV label="MAC" value={node.mac || "--"} mono />
        <KV label="Firmware" value={node.firmware_version || "--"} mono />
        <KV label="ID Nút" value={String(node.node_id)} mono />
      </div>
    </div>
  );
}

function KV({ label, value, mono = false }: { label: string; value: string; mono?: boolean }) {
  return (
    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
      <span style={{ color: "var(--text-muted)", fontSize: 11 }}>{label}</span>
      <span className={mono ? "mono" : ""} style={{ color: "var(--text-secondary)", fontSize: 12 }}>{value}</span>
    </div>
  );
}

export default Dashboard;

import { useEffect, useRef } from "react";
import type { Demo, Frame } from "../types";
import { linkHealth, linkWidth } from "../lib/health";

interface Props {
  demo: Demo;
  frame: Frame;
  title: string;
  height?: number;
}

export function TopologyCanvas({ demo, frame, title, height = 320 }: Props) {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const context = canvas.getContext("2d");
    if (!context) return;

    const ratio = window.devicePixelRatio || 1;
    const width = canvas.clientWidth;
    canvas.width = width * ratio;
    canvas.height = height * ratio;
    context.setTransform(ratio, 0, 0, ratio, 0, 0);
    context.clearRect(0, 0, width, height);

    const pad = 24;
    const xs = demo.nodes.map((n) => n.x);
    const ys = demo.nodes.map((n) => n.y);
    const minX = Math.min(...xs);
    const maxX = Math.max(...xs);
    const minY = Math.min(...ys);
    const maxY = Math.max(...ys);
    const project = (x: number, y: number): [number, number] => [
      pad + ((x - minX) / (maxX - minX || 1)) * (width - 2 * pad),
      pad + ((y - minY) / (maxY - minY || 1)) * (height - 2 * pad),
    ];

    demo.links.forEach((link, index) => {
      const isDown = frame.linkDown[index] === 1;
      const utilisation = frame.util[index] ?? 0;
      const health = linkHealth(utilisation, isDown);
      const [x1, y1] = project(demo.nodes[link.src].x, demo.nodes[link.src].y);
      const [x2, y2] = project(demo.nodes[link.dst].x, demo.nodes[link.dst].y);
      context.beginPath();
      context.setLineDash(health.dash);
      context.strokeStyle = health.colour;
      context.lineWidth = linkWidth(utilisation, isDown);
      context.moveTo(x1, y1);
      context.lineTo(x2, y2);
      context.stroke();
    });
    context.setLineDash([]);

    demo.nodes.forEach((node, index) => {
      const isDown = frame.nodeDown[index] === 1;
      const [x, y] = project(node.x, node.y);
      context.beginPath();
      context.fillStyle = isDown ? "#f26a6a" : "#cfe3ff";
      context.strokeStyle = "#0b1020";
      context.lineWidth = 1.5;
      if (isDown) {
        context.rect(x - 5, y - 5, 10, 10);
      } else {
        context.arc(x, y, 4.5, 0, Math.PI * 2);
      }
      context.fill();
      context.stroke();
      if (isDown) {
        context.fillStyle = "#0b1020";
        context.font = "bold 9px ui-sans-serif, system-ui";
        context.textAlign = "center";
        context.textBaseline = "middle";
        context.fillText("✕", x, y + 0.5);
      }
    });
  }, [demo, frame, height]);

  const downLinks = frame.linkDown.filter((v) => v === 1).length;
  const downNodes = frame.nodeDown.filter((v) => v === 1).length;
  const saturated = frame.util.filter((u, i) => frame.linkDown[i] === 0 && u >= 0.95).length;

  return (
    <figure className="m-0">
      <figcaption className="mb-1 flex items-baseline justify-between text-sm">
        <span className="font-semibold">{title}</span>
        <span className="text-xs text-slate-300">
          tick {frame.t} · {downNodes} node{downNodes === 1 ? "" : "s"} down · {downLinks} link
          {downLinks === 1 ? "" : "s"} down · {saturated} saturated
        </span>
      </figcaption>
      <canvas
        ref={canvasRef}
        role="img"
        aria-label={`${title} topology at tick ${frame.t}: ${downNodes} nodes down, ${downLinks} links down, ${saturated} links saturated`}
        style={{ width: "100%", height }}
        className="rounded border border-slate-700 bg-slate-950"
      />
    </figure>
  );
}

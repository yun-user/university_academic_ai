import { useState } from "react";

export default function PixelGuide({ thinking = false }: { thinking?: boolean }) {
  const [paused, setPaused] = useState(false);
  return (
    <div className={`pixel-guide ${thinking ? "thinking" : "ready"} ${paused ? "paused" : ""}`}>
      <svg className="pixel-scene" viewBox="0 0 80 64" shapeRendering="crispEdges" aria-hidden="true">
        <path fill="#cfdfd2" d="M10 54h60v2H10zM6 58h68v2H6z" />
        <g className="pixel-spark" fill="#d9a84a">
          <path d="M8 13h3v3h3v3h-3v3H8v-3H5v-3h3zM68 29h2v2h2v2h-2v2h-2v-2h-2v-2h2z" />
        </g>
        <g className="pixel-bot">
          <path fill="#244b40" d="M38 6h4v10h-4zM24 16h32v4h4v24h-4v8H24v-8h-4V20h4z" />
          <path fill="#91bca2" d="M28 20h24v4h4v16H24V24h4zM28 44h24v4H28z" />
          <path fill="#e3efc8" d="M28 24h24v12H28z" />
          <g className="pixel-eyes" fill="#244b40">
            <path d="M31 27h4v5h-4zM45 27h4v5h-4z" />
          </g>
          <path fill="#648a77" d="M38 33h4v2h-4zM28 52h8v4h-8zM44 52h8v4h-8z" />
          <path className="pixel-antenna" fill="#e7ba5b" d="M36 4h8v6h-8z" />
          <g className="pixel-book">
            <path fill="#244b40" d="M17 37h18l5 3 5-3h18v15H45l-5 3-5-3H17z" />
            <path fill="#fff6d7" d="M20 40h14l4 3v8l-4-2H20zM46 40h14v9H46l-4 2v-8z" />
            <path fill="#d9b55c" d="M23 43h10v2H23zM47 43h10v2H47zM23 47h7v1h-7zM47 47h7v1h-7z" />
          </g>
          <path fill="#91bca2" d="M16 42h6v6h-6zM58 42h6v6h-6z" />
        </g>
        <g className="pixel-thought" fill="#648a77">
          <rect x="58" y="10" width="3" height="3" />
          <rect x="64" y="10" width="3" height="3" />
          <rect x="70" y="10" width="3" height="3" />
        </g>
      </svg>
      <div className="pixel-guide-copy">
        <span className="eyebrow">PATH AI</span>
        <p role="status">{thinking ? "이수 내역을 살펴보고 답변을 정리하고 있어요…" : "다음 한 학기, 함께 준비해요."}</p>
        <small>{thinking ? "잠시만 기다려 주세요." : "궁금한 점과 원하는 계획을 알려 주세요."}</small>
      </div>
      <button type="button" className="text-button pixel-toggle" aria-pressed={paused}
        onClick={() => setPaused(!paused)}>
        {paused ? "애니메이션 재생" : "애니메이션 멈춤"}
      </button>
    </div>
  );
}

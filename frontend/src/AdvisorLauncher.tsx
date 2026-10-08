import { useState } from "react";

export default function AdvisorLauncher({ onOpen, disabled }: { onOpen: () => void; disabled: boolean }) {
  const [paused, setPaused] = useState(false);
  return <div className={`advisor-launcher ${paused ? "paused" : ""}`}>
    <button type="button" className="advisor-launcher-open" onClick={onOpen} disabled={disabled} aria-label="상담이 필요하신가요? AI 졸업 상담 열기">
      <span className="advisor-speech">상담이 필요하신가요?</span>
      <svg className="advisor-character" viewBox="0 0 64 64" shapeRendering="crispEdges" aria-hidden="true">
        <path fill="#dbe6d8" d="M17 59h34v3H17z" />
        <g className="pixel-bot">
          <path fill="#244b40" d="M29 7h4v9h-4zM17 16h30v4h4v25h-4v10H17V45h-4V20h4z" />
          <path fill="#9ac3a8" d="M21 20h22v4h4v17H17V24h4zM21 45h22v6H21z" />
          <path fill="#f3f4ce" d="M21 24h22v13H21z" />
          <g className="pixel-eyes" fill="#244b40"><path d="M24 27h4v5h-4zM37 27h4v5h-4z" /></g>
          <path fill="#648a77" d="M29 34h7v2h-7zM20 55h9v4h-9zM37 55h9v4h-9zM8 37h7v11H8z" />
          <path className="pixel-antenna" fill="#e7ba5b" d="M27 4h8v6h-8z" />
          <g className="advisor-wave"><path fill="#244b40" d="M49 35h5v-9h7v16h-4v4h-8z" /><path fill="#9ac3a8" d="M52 36h5v-7h2v10h-3v4h-4z" /></g>
          <path fill="#fff6d7" d="M27 45h10v3H27z" />
        </g>
        <path className="pixel-spark" fill="#d9a84a" d="M7 9h2v3h3v2H9v3H7v-3H4v-2h3zM53 12h3v3h-3z" />
      </svg>
    </button>
    <button className="advisor-motion text-button" type="button" aria-pressed={paused} onClick={() => setPaused(!paused)} aria-label={paused ? "상담 캐릭터 움직임 재생" : "상담 캐릭터 움직임 멈춤"}>{paused ? "재생" : "멈춤"}</button>
  </div>;
}

import React from "react";

// FraudLens mark (same geometry as web/src/components/LensMark.tsx): a lens over a three-node graph.
export const LensMark: React.FC<{ size?: number; style?: React.CSSProperties }> = ({ size = 64, style }) => (
  <svg width={size} height={size} viewBox="0 0 32 32" style={style}>
    <circle cx="13.5" cy="13.5" r="9.5" fill="none" stroke="#F58025" strokeWidth="2.4" />
    <path d="M20.6 20.6 28 28" stroke="#F58025" strokeWidth="3.2" strokeLinecap="round" />
    <path d="M9.5 16.5 13.5 9.5 17.5 15.5 Z" fill="none" stroke="#E7EBF1" strokeOpacity="0.55" strokeWidth="1.2" strokeLinejoin="round" />
    <circle cx="9.5" cy="16.5" r="1.9" fill="#E7EBF1" />
    <circle cx="17.5" cy="15.5" r="1.9" fill="#E7EBF1" />
    <circle cx="13.5" cy="9.5" r="2.3" fill="#F58025" />
  </svg>
);

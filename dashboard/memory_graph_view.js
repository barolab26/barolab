(function (root) {
  'use strict';
  function normalizeGraph(data) {
    if (!data || !Array.isArray(data.nodes) || !Array.isArray(data.edges)) throw new Error('그래프 응답 형식이 올바르지 않습니다.');
    const nodes = data.nodes.map((node, index) => ({ ...node, id: node.id || node.rel || String(index), label: node.label || node.title || node.rel || String(index), deg: 0 }));
    const edges = data.edges.map(edge => {
      if (!Array.isArray(edge) || edge.length !== 2 || !edge.every(i => Number.isInteger(i) && i >= 0 && i < nodes.length)) throw new Error('그래프 연결의 노드 번호가 올바르지 않습니다.');
      nodes[edge[0]].deg++; nodes[edge[1]].deg++;
      return edge.slice();
    });
    return { nodes, edges };
  }
  function canvasSize(width, height, ratio) {
    const w = Number.isFinite(width) && width > 0 ? width : 860;
    const h = Number.isFinite(height) && height > 0 ? height : 580;
    const dpr = Math.max(1, Math.min(Number.isFinite(ratio) ? ratio : 1, 2));
    return { width: w, height: h, dpr, pixelWidth: Math.max(1, Math.round(w * dpr)), pixelHeight: Math.max(1, Math.round(h * dpr)) };
  }
  function cameraFor(points, width, height) {
    const valid = points.filter(p => Number.isFinite(p.x) && Number.isFinite(p.y));
    if (!valid.length) return { x: width / 2, y: height / 2, s: 1 };
    const xs = valid.map(p => p.x), ys = valid.map(p => p.y);
    const minX = Math.min(...xs), maxX = Math.max(...xs), minY = Math.min(...ys), maxY = Math.max(...ys);
    const s = Math.max(0.001, Math.min(Math.max(40, width - 200) / Math.max(maxX - minX, 180), Math.max(40, height - 200) / Math.max(maxY - minY, 150), 2.2));
    return { s, x: width / 2 - (minX + maxX) * s / 2, y: height / 2 - (minY + maxY) * s / 2 };
  }
  function graphRevision(data) { return JSON.stringify({nodes:data.nodes,edges:data.edges}); }
  function nodeShape(node) { return node.isCoreHub === true ? 'star' : 'diamond'; }
  const api = { normalizeGraph, canvasSize, cameraFor, nodeShape, graphRevision };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else root.MemoryGraphView = api;
})(typeof window !== 'undefined' ? window : globalThis);

(function (root) {
  'use strict';
  const contractVersion='memory-knowledge-gate-v1';
  function assertContract(data) {
    if(data?.contractVersion!==contractVersion || !Number.isSafeInteger(data?.quarantine?.count) || data.quarantine.count<0) {
      throw new Error('검증 게이트 API 계약 버전이 일치하지 않습니다.');
    }
    return normalizeGraph(data);
  }
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
    const side = Math.min(width / 3, Math.max(28, ...valid.map(p => (p.labelWidth || 140) / 2 + 12)));
    const top = 32, bottom = 76;
    const s = Math.max(0.001, Math.min(Math.max(20, width - side * 2) / Math.max(maxX - minX, 180), Math.max(20, height - top - bottom) / Math.max(maxY - minY, 150), 2.2));
    return { s, x: width / 2 - (minX + maxX) * s / 2, y: top + (height - top - bottom) / 2 - (minY + maxY) * s / 2 };
  }
  function overlaps(a,b,gap=5) { return a.x < b.x+b.width+gap && a.x+a.width+gap > b.x && a.y < b.y+b.height+gap && a.y+a.height+gap > b.y; }
  // Labels use screen pixels. Choose non-overlapping labels without dropping nodes.
  function visibleLabels(candidates,width,height,reserved=[]) {
    const occupied=reserved.slice(), visible=[];
    for(const label of [...candidates].sort((a,b)=>(b.priority||0)-(a.priority||0)||a.index-b.index)) {
      if(label.x<6 || label.y<6 || label.x+label.width>width-6 || label.y+label.height>height-6 || occupied.some(box=>overlaps(label,box))) continue;
      visible.push(label.index); occupied.push(label);
    }
    return visible;
  }
  // Measured capsule envelopes replace a fixed ellipse. Resolve after integration
  // so velocity cannot undo separation; pinned nodes remain where the user put them.
  function separatePoints(points,iterations=3) {
    for(let pass=0;pass<iterations;pass++) for(let i=0;i<points.length;i++) for(let j=i+1;j<points.length;j++) {
      const a=points[i],b=points[j];
      const dx=b.x-a.x,dy=b.y-a.y;
      const ox=((a.labelWidth||140)+(b.labelWidth||140))/2+28-Math.abs(dx);
      const oy=100-Math.abs(dy);
      if(ox<=0||oy<=0)continue;
      const fixedA=a.fx!=null,fixedB=b.fx!=null;
      if(fixedA&&fixedB)continue;
      const moveA=fixedA?0:fixedB?1:0.5,moveB=fixedB?0:fixedA?1:0.5;
      if(ox<oy) {const d=(dx<0?-1:1)*(ox+0.1);a.x-=d*moveA;b.x+=d*moveB;}
      else {const d=(dy<0?-1:1)*(oy+0.1);a.y-=d*moveA;b.y+=d*moveB;}
    }
  }
  function placeLabels(candidates,width,height,glyphs=[],reserved=[]) {
    const placed=[];
    const fits=(box,blocks)=>box.x>=6 && box.y>=6 && box.x+box.width<=width-6 && box.y+box.height<=height-6 && !blocks.some(other=>overlaps(box,other));
    for(const label of [...candidates].sort((a,b)=>(b.priority||0)-(a.priority||0)||a.index-b.index)) {
      let options=[label];
      if(label.important) {
        options.push({...label,y:label.y-label.height-45},{...label,x:label.x-label.width-20},{...label,x:label.x+label.width+20});
        for(let row=0;row<8;row++) for(const x of [6,width-label.width-6]) options.push({...label,x,y:8+row*(label.height+8)});
      }
      const blocked=[...reserved,...placed];
      let chosen=options.find(box=>fits(box,[...glyphs,...blocked]));
      // Dense small glyphs must not hide a major node's readable title.
      if(!chosen && label.important) chosen=options.find(box=>fits(box,blocked));
      if(chosen) placed.push(chosen);
    }
    return placed;
  }
  function graphRevision(data) { return JSON.stringify({nodes:data.nodes,edges:data.edges,quarantine:data.quarantine,quarantined:data.stats?.quarantined}); }
  function filterGraph(graph,category) {
    if(category!=='skill')return graph;
    const keep=new Set(graph.nodes.map((node,index)=>isSkill(node)?index:-1).filter(index=>index>=0));
    for(const [a,b] of graph.edges) {
      if(keep.has(a)&&graph.nodes[b].isCoreHub)keep.add(b);
      if(keep.has(b)&&graph.nodes[a].isCoreHub)keep.add(a);
    }
    const remap=new Map(),nodes=[];
    graph.nodes.forEach((node,index)=>{if(keep.has(index)){remap.set(index,nodes.length);nodes.push(node);}});
    return normalizeGraph({nodes,edges:graph.edges.filter(([a,b])=>remap.has(a)&&remap.has(b)).map(([a,b])=>[remap.get(a),remap.get(b)])});
  }
  function isSkill(node) { return node.category==='skill' && !node.isCoreHub && (node.verifiedKnowledge===true || node.knowledgeStatus==='curated_procedure'); }
  function quarantineLabel(data) {
    const count=data?.quarantine?.count ?? data?.stats?.quarantined;
    return Number.isSafeInteger(count)&&count>=0?`수집 제외 ${count}개 · 원문 보존`:'수집 제외 수 확인 중';
  }
  function wrapLabel(value,maxWidth,measure) {
    const lines=[];let line='';
    for(const char of String(value||'')) {if(line && measure(line+char)>maxWidth){lines.push(line);line='';}line+=char;}
    lines.push(line);return lines;
  }
  function nodeShape(node) { return node.isCoreHub === true ? 'star' : 'diamond'; }
  const api = { normalizeGraph, canvasSize, cameraFor, nodeShape, graphRevision, overlaps, visibleLabels, placeLabels, separatePoints, filterGraph, wrapLabel, isSkill, quarantineLabel, assertContract, contractVersion };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else root.MemoryGraphView = api;
})(typeof window !== 'undefined' ? window : globalThis);

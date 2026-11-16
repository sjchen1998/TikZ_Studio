const INIT_CODE = String.raw`\begin{circuitikz}[font=\small, european]
  \ctikzset{bipoles/length=1.0cm, bipoles/thickness=1.2}
  % 次级端子 → 引线 → 交流结点
  \draw (0,2.0) node[left] {次级\,$+$}
    to[short, o-] (1.2,2.0) coordinate (acp);
  \draw (0,0.0) node[left] {次级\,$-$}
    to[short, o-] (1.2,0.0) coordinate (acn);
  \filldraw (acp) circle (1.2pt);
  \filldraw (acn) circle (1.2pt);
  % 交流母线向右延伸，供桥臂与 TVS 搭接
  \draw (acp) -- (2.4,2.0) coordinate (acpr);
  \draw (acn) -- (2.4,0.0) coordinate (acnr);
  \filldraw (acpr) circle (1.2pt);
  \filldraw (acnr) circle (1.2pt);
  \draw (acp) to[zzD, l_={TVS}] (acn);
  % 直流结点与桥臂（压缩上下跨距，避免图题下方留白）
  \coordinate (dcp) at (4.6,3.0);
  \coordinate (dcn) at (4.6,-1.0);
  \draw (acpr) to[D*, l=$D_1$] (dcp);
  \draw (acnr) to[D*, l_=$D_3$] (dcp);
  \draw (dcn)  to[D*, l_=$D_2$] (acpr);
  \draw (dcn)  to[D*, l=$D_4$] (acnr);
  \filldraw (dcp) circle (1.2pt);
  \filldraw (dcn) circle (1.2pt);
  % 储能与旁路
  \draw (dcp) to[C, l=$C_{\mathrm{bus}}$] (dcn);
  \draw (dcp) -- (6.2,3.0) coordinate (vo);
  \draw (dcn) -- (6.2,-1.0) coordinate (vog);
  \draw (vo) to[C] (vog);
  \node[right=6pt] at ($(vo)!0.5!(vog)$) {$C_{\mathrm{HF}}$};
  \filldraw (vo) circle (1.2pt);
  \filldraw (vog) circle (1.2pt);
  % 母线双线输出（标注放在线端右侧，不向下撑开包围盒）
  \draw (vo)  -- ++(1.4,0) node[right] {$V_{\mathrm{bus}}^+$};
  \draw (vog) -- ++(1.4,0) node[right] {$V_{\mathrm{bus}}^-$};
  \useasboundingbox (-1.6,-1.35) rectangle (9.0,3.55);
\end{circuitikz}`;
const TPLS = {
  rc: "\\begin{circuitikz}[font=\\small, european]\n  \\draw (0,0) to[V, l=$V_{in}$] (0,3) to[R, l=$R_1$] (3,3) to[C, l=$C_1$] (3,0) -- (0,0);\n  \\node[circ] at (3,3) {};\n  \\draw (3,3) -- (4.5,3) node[right] {$V_{out}$};\n\\end{circuitikz}",
  buck: "\\begin{circuitikz}[font=\\small, european]\n  \\draw (0,0) node[ground]{} to[V, l=$V_{in}$] (0,3) to[nos, l=$Q_1$] (2.5,3) to[L, l=$L_1$] (5.5,3) -- (7,3) node[right]{$V_{out}$};\n  \\draw (2.5,0) node[ground]{} to[D*, l=$D_1$] (2.5,3);\n  \\draw (5.5,3) to[C, l=$C_o$] (5.5,0) node[ground]{};\n\\end{circuitikz}",
  opamp: "\\begin{circuitikz}[font=\\small, european]\n  \\node[op amp] (op) at (3,2) {};\n  \\draw (0,1.5) node[left]{$V_{in}$} -- (op.+);\n  \\draw (op.-) -- (1.8,2.5) -- (1.8,3.6) to[R, l=$R_f$] (4.2,3.6) -| (op.out);\n  \\draw (1.8,2.5) to[R, l=$R_1$] (1.8,0.5) node[ground]{};\n  \\draw (op.out) -- (5,2) node[right]{$V_{out}$};\n\\end{circuitikz}",
  block: "\\begin{tikzpicture}[>=Stealth, font=\\small]\n  \\node[draw, rounded corners, minimum width=1.8cm, minimum height=0.9cm] (a) at (0,0) {传感器};\n  \\node[draw, rounded corners, minimum width=2cm, minimum height=0.9cm] (b) at (3.5,0) {DSP};\n  \\draw[->] (a) -- (b);\n\\end{tikzpicture}",
  plot: "\\begin{tikzpicture}[font=\\small]\n  \\begin{axis}[width=8cm, height=5cm, grid=major, tick label style={font=\\small}, label style={font=\\small}]\n    \\addplot[blue, thick, domain=0:6, samples=80] {3.3 * (1 - exp(-x))};\n  \\end{axis}\n\\end{tikzpicture}",
  plane: String.raw`\begin{tikzpicture}[font=\small]
    % 1. 绘制网格（可选，若不需要可注释掉）
    \draw[step=1cm, gray!30, very thin] (-3.9,-2.9) grid (4.9,4.9);

    % 2. 绘制坐标轴 (x轴与y轴)，并带箭头
    \draw[->, thick] (-4,0) -- (5,0) node[right] {$x$};
    \draw[->, thick] (0,-3) -- (0,5) node[above] {$y$};

    % 3. 绘制刻度与数字
    \foreach \x in {-3,-2,-1,1,2,3,4}
        \draw (\x, 0.05) -- (\x, -0.05) node[below] {\x};
    \foreach \y in {-2,-1,1,2,3,4}
        \draw (0.05, \y) -- (-0.05, \y) node[left] {\y};
    \node at (-0.3, -0.3) {$O$}; % 原点

    % 4. 绘制点
    \coordinate (A) at (2, 3);
    \filldraw[red] (A) circle (2pt) node[above right] {$A(2,3)$};

    % 5. 绘制线段
    \draw[blue, thick] (-2,-1) -- (2,3) node[midway, above left] {线段};

    % 6. 绘制函数图像 (例如抛物线 y = 0.5*x^2 - 1)
    \draw[domain=-2.8:2.8, smooth, variable=\x, red, thick]
        plot ({\x}, {0.5*\x*\x - 1});

\end{tikzpicture}`,
  cms: String.raw`\colorlet{myred}{red!70!black}
\colorlet{mycontourred}{red!55!black!3}
\colorlet{mycontourred2}{red!55!black!6}
\colorlet{mydarkred}{red!40!black}
\colorlet{CMScol}{red!80!black}
\contourlength{0.9pt}
\tikzset{>=latex}
\tikzset{axis/.style={->,thick,line cap=round}}
\tikzset{detector/.style={thick,draw=mydarkred,rotate around z=\ang}}
\tikzset{beam pipe/.style={draw=blue!20!black!50,fill=blue!20!black!10,rotate around z=\ang}}
\tikzset{detector surface/.style={red!60!black!10,opacity=0.5,rotate around z=\ang}}
\providecommand*{\vv}[1]{\vec{\mkern0mu#1}}
% CMS detector - east perspective
\tdplotsetmaincoords{70}{125}
\begin{tikzpicture}[tdplot_main_coords,rotate around x=90,font=\small]
  \coordinate (O) at (0,0,0);
  \coordinate (Z) at (0,0,4.34);
  \tdplotsetcoord{O'}{3.472/cos(17)}{17}{60}
  \tdplotsetcoord{O''}{0.0504}{90}{60}
  \tdplotsetcoord{P}{4.34/cos(17)}{17}{60}
  \def\ang{24}
  \fill[top color=red!50!black!4,bottom color=red!60!black!2,rotate around z=\ang]
    (0,2.1,4.34) --++ (0,0,-8.68) arc(90:270:2.1) --++ (0,0,8.68) arc(270:90:2.1) -- cycle;
  \fill[detector surface]
    (0,0,4.34) --++ (0,2.1,0) arc(90:270:2.1) -- cycle;
  \fill[detector surface]
    (0,0,-4.34) --++ (0,2.1,0) arc(90:270:2.1) -- cycle;
  \tdplotdrawarc[detector,thin]{(0,0,4.34)}{2.1}{0}{360}{}{}
  \tdplotdrawarc[detector]{(0,0,-4.34)}{2.1}{0}{360}{}{}
  \draw[detector,thin] (90:2.1) arc (90:270:2.1);
  \draw[detector,very thin] (90:2.1) arc (90:90-\ang:2.1);
  \draw[detector] (0,0,-4.34)++(90:2.1) --++ (0,0,8.68);
  \draw[detector] (0,0,-4.34)++(-90:2.1) --++ (0,0,8.68);
  \tdplotdrawarc[beam pipe]{(0,0,-5.74)}{0.112}{0}{360}{}{}
  \draw[beam pipe]
    (0,0.112,-5.74) -- (0,0.112,-2.296) -- (90:0.056)
    -- (0,0.112,2.296) -- (0,0.112,5.74) arc(90:-90:0.112)
    -- (0,-0.112,2.296) -- (-90:0.056) --
    (0,-0.112,-2.296) -- (0,-0.112,-5.74) arc(-90:90:0.112);
  \draw[beam pipe] (0,0,5.74) circle(0.112);
  \draw[axis] (0,0,0) -- (0,0,6.58) node[anchor=north,xshift=3pt,yshift=-2pt]{$z$};
  \fill[CMScol] (O) circle(0.5pt) node[anchor=north,xshift=1pt,yshift=-1pt] {IP};
  \draw[axis,-] (0,0,-6.3) -- (0,0,-0.056);
  \draw[axis] (0,0.0532,0) -- (0,2.94,0) node[below left]{$y$};
  \draw[axis] (0.0616,0,0) -- (2.8,0,0) node[anchor=east,xshift=2pt,yshift=-1pt]{$x$};
  \draw[red] (O) -- (O');
  \node[mydarkred,above] at (0,2.94,0) {$\eta=0$};
  \node[mydarkred,anchor=south,yshift=6pt] at (0,2.1,1.9964) {$\eta>0$};
  \node[mydarkred,anchor=south,yshift=6pt] at (0,2.1,-2.604) {$\eta<0$};
  \node[mydarkred,anchor=east,yshift=1pt] at (0,0,6.58) {$\eta=+\infty$};
  \node[mydarkred,anchor=west,yshift=-1pt] at (0,0,-6.3) {$\eta=-\infty$};
  \draw[beam pipe,fill=none] (0,0.112,-5.74) arc(90:-90:0.112);
  \fill[detector surface]
    (0,0.1176,4.34) --++ (0,1.9824,0) arc(90:-90:2.1) --++ (0,1.9824,0) arc(-90:90:0.1176);
  \fill[detector surface]
    (0,0.1176,-4.34) --++ (0,1.9824,0) arc(90:-90:2.1) --++ (0,1.9824,0) arc(-90:90:0.1176);
  \tdplotdrawarc[detector]{(0,0,4.34)}{2.1}{-90}{90.1}{}{}
  \tdplotdrawarc[detector]{(0,0,-4.34)}{2.1}{-90}{90}{}{}
  \draw[beam pipe,fill=none] (0,0.112,5.74) arc(90:-90:0.112);
  \draw[detector,very thin] (90-\ang:2.1) arc (90-\ang:-90:2.1);
  \draw[detector,very thin] (90-\ang:2.1) arc (90-\ang:-90:2.1);
  \draw[dashed,myred] (Pz) -- (P);
  \draw[->,red,line cap=round] (O'') -- (Pxy) node[anchor=-92] {$\vv{p}_\mathrm{T}$};
  \draw[dashed,myred,line join=round] (Py) -- (Pxy) -- (P);
  \draw[->,red] (O') -- (P) node[anchor=-50,inner sep=1pt] {$\vv{p}$};
  \tdplotdrawarc[thick,mycontourred]{(O)}{0.56}{4}{42}{}{}
  \tdplotdrawarc[draw=none,opacity=0.9]{(O)}{0.56}{0}{60}
    {anchor=mid east,xshift=1pt,yshift=-4pt}{\contour{mycontourred}{$\phi$}}
  \tdplotdrawarc[->]{(O)}{0.56}{0}{60}
    {anchor=mid east,xshift=1pt,yshift=-4pt}{$\phi$}
  \tdplotdrawarc[->,rotate around z=-30,rotate around y=-90]
    {(O)}{2.94}{0}{17}{anchor=mid east,yshift=2pt}{$\theta$}
  \tdplotdrawarc[-{>[bend=1]},rotate around z=-30,rotate around y=-90,line cap=round]
    {(O)}{0.84}{90}{17}{anchor=mid east,xshift=2pt,yshift=4pt}{$\eta$}
  \draw[mydarkred,line cap=round] (0.0112,0,4.34) --++ (2.1,0,0);
  \tdplotdrawarc[thick,mycontourred2]{(Z)}{0.56}{4}{42}{}{}
  \tdplotdrawarc[draw=none]{(Z)}{0.56}{0}{60}
    {anchor=mid east,xshift=1pt,yshift=-4pt,opacity=0.9}{\contour{mycontourred2}{$\phi$}}
  \tdplotdrawarc[->]{(Z)}{0.56}{0}{60}
    {anchor=mid east,xshift=1pt,yshift=-4pt}{$\phi$}
  \begin{scope}[shift={(2.73,-2.1,3.906)},rotate around y=12]
    \draw[<->,black!50] (-0.84,0,0) -- (0.84,0,0);
    \draw[<->,black!50] (0,0,-0.84) -- (0,0,0.84);
    \node[anchor=south,xshift=4pt,black!50] at (-0.84,0,0) {N};
    \node[anchor=east,xshift=1pt,yshift=1pt,green!20!black!50] at (0,0,0.84) {Jura};
    \node[anchor=north,xshift=-2pt,yshift=-1pt,blue!30!black!50] at (0.84,0,0) {ATLAS};
  \end{scope}
  \draw[->,thick,orange!30!black] (1.176,-2.1,0.868) --++ (1.68,0,0)
    node[anchor=east,yshift=-1pt,align=center] {center of\\[-1pt]the LHC};
\end{tikzpicture}`,
  gauss: String.raw`\pgfmathdeclarefunction{gauss}{3}{%
  \pgfmathparse{1/(#3*sqrt(2*pi))*exp(-((#1-#2)^2)/(2*#3^2))}%
}
\colorlet{mydarkblue}{blue!30!black}
\def\N{50}
% GAUSSIANs: 68-95-99 rule
\begin{tikzpicture}[font=\small]
  \def\B{11}
  \def\Bs{3.0}
  \def\xmax{\B+3.2*\Bs}
  \def\ymin{{-0.1*gauss(\B,\B,\Bs)}}
  \def\h{0.08*gauss(\B,\B,\Bs)}
  \begin{axis}[every axis plot post/.append style={
               mark=none,domain={-0.05*(\xmax)}:{1.08*\xmax},samples=\N},
               xmin={-0.1*(\xmax)}, xmax=\xmax,
               ymin=\ymin, ymax={1.1*gauss(\B,\B,\Bs)},
               axis lines=middle,
               axis line style=thick,
               enlargelimits=upper,
               ticks=none,
               xlabel=$x$,
               every axis x label/.style={at={(current axis.right of origin)},anchor=north,font=\small},
               width=0.85*\textwidth, height=0.55*\textwidth,
               y=700pt,
               clip=false,
               every node/.append style={font=\small}]
    \addplot[blue,thick,smooth,name path=B] {gauss(x,\B,\Bs)};
    \path[name path=xaxis] (0,0) -- (\pgfkeysvalueof{/pgfplots/xmax},0);
    \addplot[blue!50] fill between[of=xaxis and B, soft clip={domain={\B-3*\Bs}:{\B+3*\Bs}}];
    \addplot[blue!25] fill between[of=xaxis and B, soft clip={domain={\B-2*\Bs}:{\B+2*\Bs}}];
    \addplot[blue!10] fill between[of=xaxis and B, soft clip={domain={\B-1*\Bs}:{\B+1*\Bs}}];
    \addplot[black,dashed,thick]
      coordinates {({\B-3*\Bs},{20*gauss(\B-3*\Bs,\B,\Bs)}) ({\B-3*\Bs},{-\h})}
      node[below=-3pt] {\strut$\mu-3\sigma$};
    \addplot[black,dashed,thick]
      coordinates {({\B-2*\Bs},{4*gauss(\B-2*\Bs,\B,\Bs)}) ({\B-2*\Bs},{-\h})}
      node[below=-3pt] {\strut$\mu-2\sigma$};
    \addplot[black,dashed,thick]
      coordinates {({\B-1*\Bs},{1.3*gauss(\B-\Bs,\B,\Bs)}) ({\B-1*\Bs},{-\h})}
      node[below=-3pt] at ({\B-\Bs},{-\h}) {\strut$\mu-\sigma$};
    \addplot[black,dashed,line width=0.7pt]
      coordinates {(\B,{1.05*gauss(\B,\B,\Bs)}) (\B,{-\h})}
      node[below=-3pt] {\strut$\mu$};
    \addplot[black,dashed,thick]
      coordinates {({\B+1*\Bs},{1.3*gauss(\B+\Bs,\B,\Bs)}) ({\B+1*\Bs},{-\h})}
      node[below=-3pt] at ({\B+\Bs},{-\h}) {\strut$\mu+\sigma$};
    \addplot[black,dashed,thick]
      coordinates {({\B+2*\Bs},{4*gauss(\B+2*\Bs,\B,\Bs)}) ({\B+2*\Bs},{-\h})}
      node[below=-3pt] at ({\B+2*\Bs},{-\h}) {\strut$\mu+2\sigma$};
    \addplot[black,dashed,thick]
      coordinates {({\B+3*\Bs},{20*gauss(\B+3*\Bs,\B,\Bs)}) ({\B+3*\Bs},{-\h})}
      node[below=-3pt] at ({\B+3*\Bs},{-\h}) {\strut$\mu+3\sigma$};
    \addplot[<->,mydarkblue,thick]
      coordinates {({\B-\Bs},{.55*gauss(\B,\B,\Bs)}) ({\B+\Bs},{.55*gauss(\B,\B,\Bs)})};
    \addplot[<->,mydarkblue,thick]
      coordinates {({\B-2*\Bs},{.35*gauss(\B,\B,\Bs)}) ({\B+2*\Bs},{.35*gauss(\B,\B,\Bs)})};
    \addplot[<->,mydarkblue,thick]
      coordinates {({\B-3*\Bs},{.15*gauss(\B,\B,\Bs)}) ({\B+3*\Bs},{.15*gauss(\B,\B,\Bs)})};
    \node[mydarkblue,fill=blue!10,inner xsep=3pt,inner ysep=1pt]
      at (\B,{.55*gauss(\B,\B,\Bs)}) {68.3\%};
    \node[mydarkblue,fill=blue!10,inner xsep=3pt,inner ysep=2pt]
      at (\B,{.35*gauss(\B,\B,\Bs)}) {95.5\%};
    \node[mydarkblue,fill=blue!10,inner xsep=3pt,inner ysep=2pt]
      at (\B,{.15*gauss(\B,\B,\Bs)}) {99.7\%};
  \end{axis}
\end{tikzpicture}`,
  freq: String.raw`\colorlet{xcol}{blue!60!black}
\colorlet{myred}{red!80!black}
\colorlet{myblue}{blue!80!black}
\colorlet{mygreen}{green!40!black}
\colorlet{myorange}{orange!90!black}
\colorlet{mydarkred}{myred!80!black}
\tikzset{>=latex}
\tikzset{xline/.style={xcol,thick}}
\def\tick#1#2{\draw[thick] (#1)++(#2:0.12) --++ (#2-180:0.24)}
\def\N{100}
% RESONANCE
\begin{tikzpicture}[font=\small]
  \def\xmax{4.5}
  \def\ymax{2.7}
  \def\c{1.4}
  \def\A{0.90*\ymax}
  \def\ba{0.3}
  \def\bb{0.9}
  \def\bc{2.0}
  \def\bd{8.0}
  \coordinate (O) at (0,0);
  \coordinate (X) at (\xmax,0);
  \coordinate (Y) at (0,\ymax);
  \coordinate (C) at (\c,0);
  \draw[->,thick] (-0.1*\ymax,0) -- (\xmax,0) node[below] {$\omega$};
  \draw[->,thick] (0,-0.1*\ymax) -- (0,\ymax) node[below left] {$A$};
  \draw[xline,myred,samples=\N,smooth,variable=\x,domain=0.01:0.94*\xmax]
    plot(\x,{\A*\ba*\c/sqrt((\c*\c-\x*\x)^2+(\ba*\x)^2)});
  \draw[xline,myorange,samples=\N,smooth,variable=\x,domain=0.01:0.94*\xmax]
    plot(\x,{\A*\ba*\c/sqrt((\c*\c-\x*\x)^2+(\bb*\x)^2)});
  \draw[xline,myblue,samples=\N,smooth,variable=\x,domain=0.01:0.94*\xmax]
    plot(\x,{\A*\ba*\c/sqrt((\c*\c-\x*\x)^2+(\bc*\x)^2)});
  \draw[xline,mygreen,samples=\N,smooth,variable=\x,domain=0.01:0.94*\xmax]
    plot(\x,{\A*\ba*\c/sqrt((\c*\c-\x*\x)^2+(\bd*\x)^2)});
  \node[mydarkred,align=left,right] at ({0.26*(\c+\xmax)},0.8*\A) {small $b$, $\Delta\omega$\\large $Q$};
  \node[myblue,align=left,above] at ({0.65*(\c+\xmax)},0.3*\A*\ba/\bc) {large $b$, $\Delta\omega$\\small $Q$};
  \draw[dashed,thin] (C) --++ (0,\A);
  \tick{C}{90} node[below] {$\omega_0$};
\end{tikzpicture}`
};
function P(pt) { return pt && pt.ref ? `(${pt.ref})` : `(${+Number(pt[0]).toFixed(3)},${+Number(pt[1]).toFixed(3)})`; }
function withRot(opts, rot) {
  const ang = Number(rot) || 0;
  return ang ? `${opts}, rotate=${ang}` : opts;
}
function deviceNode(kind, p, a, rot, fallback) {
  const text = String(a || '').trim();
  const named = /^[A-Za-z][A-Za-z0-9_]*$/.test(text);
  const opt = text && !named ? `${kind}, label={${text}}` : kind;
  return `\\node[${withRot(opt, rot)}] (${named ? text : fallback}) at ${P(p[0])} {};`;
}
function shiftDraw(src, pt) {
  const dx = Number(pt[0]), dy = Number(pt[1]);
  return src.replace(/\(\s*([-+]?\d*\.?\d+)\s*,\s*([-+]?\d*\.?\d+)\s*\)/g, (_, x, y) => `(${+(parseFloat(x) + dx).toFixed(3)},${+(parseFloat(y) + dy).toFixed(3)})`);
}
function placeLocal(body, pt, rot) {
  const ang = Number(rot) || 0;
  if (!ang && !(pt && pt.ref)) return shiftDraw(body, pt);
  const opt = ang ? `shift={${P(pt)}}, rotate=${ang}` : `shift={${P(pt)}}`;
  return `\\begin{scope}[${opt}]\n    ${body}\n  \\end{scope}`;
}
function relAxes(pt, rot, lines) {
  const ang = Number(rot) || 0;
  const at = ang ? '(0,0)' : P(pt);
  const body = lines.map(ln => ln.split('__at__').join(at)).join('\n  ');
  if (!ang) return body;
  return `\\begin{scope}[shift={${P(pt)}}, rotate=${ang}]\n  ${body}\n\\end{scope}`;
}
function bipole(label, tikz, def) {
  return { name: label, btn: label, n: 2, field: '标注', def, build: (p, a) => `\\draw ${P(p[0])} to[${tikz}${a ? `, l=${a}` : ''}] ${P(p[1])};` };
}
function planePoint(p, a) {
  const text = String(a || '').trim() || '$A$';
  const named = text.match(/^\$?([A-Za-z][A-Za-z0-9]*)(?:\([^$]*\))?\$?$/);
  const at = P(p[0]);
  if (!named) return `\\filldraw[red] ${at} circle (2pt) node[above right] {${text}};`;
  return `\\coordinate (${named[1]}) at ${at};\n  \\filldraw[red] (${named[1]}) circle (2pt) node[above right] {${text}};`;
}
function numOr(v, d) {
  const n = parseFloat(v);
  return Number.isFinite(n) ? n : d;
}
function spacePath(raw) {
  let s = String(raw || '').trim().replace(/;+\s*$/, '');
  if (!s) s = '(0,0,0) -- (1,1,1)';
  return s.replace(/\)\s*-(?!-)\s*\(/g, ') -- (');
}
function center3(raw) {
  let s = String(raw || '').trim();
  if (!s) return '(0,0,0)';
  if (s[0] !== '(') s = '(' + s;
  if (s[s.length - 1] !== ')') s += ')';
  return s;
}
function unit3(a) {
  const n = Math.hypot(a[0], a[1], a[2]);
  return n < 1e-9 ? null : [a[0] / n, a[1] / n, a[2] / n];
}
function cross3(a, b) {
  return [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]];
}
function fmt3(a) {
  return a.map(v => +Number(v).toFixed(5)).join(',');
}
function triplesOf(s) {
  const out = [], re = /\(?\s*([-+]?(?:\d+\.?\d*|\.\d+))\s*,\s*([-+]?(?:\d+\.?\d*|\.\d+))\s*,\s*([-+]?(?:\d+\.?\d*|\.\d+))\s*\)?/g;
  let m;
  while ((m = re.exec(s))) out.push([+m[1], +m[2], +m[3]]);
  return out;
}
function planeAxes(name) {
  const s = String(name || 'xy').trim();
  const key = s.toLowerCase();
  if (key === 'xy' || key === '') return ['1,0,0', '0,1,0'];
  if (key === 'xz' || key === 'zx') return ['1,0,0', '0,0,1'];
  if (key === 'yz' || key === 'zy') return ['0,1,0', '0,0,1'];
  const vs = triplesOf(s);
  if (vs.length >= 2) {
    const u = unit3(vs[0]);
    const n = u && unit3(cross3(u, vs[1]));
    if (!u || !n) return ['1,0,0', '0,1,0'];
    return [fmt3(u), fmt3(cross3(n, u))];
  }
  if (vs.length === 1) {
    const n = unit3(vs[0]);
    if (!n) return ['1,0,0', '0,1,0'];
    const hint = Math.abs(n[0]) > 0.9 ? [0, 1, 0] : [1, 0, 0];
    const u = unit3(cross3(hint, n));
    return [fmt3(u), fmt3(cross3(n, u))];
  }
  return ['1,0,0', '0,1,0'];
}
function arc3(v, full) {
  const c = center3(v.c);
  const r = String(v.r || '').trim() || '0.5';
  const a0 = full ? '0' : (String(v.a || '').trim() || '0');
  const a1 = full ? '360' : (String(v.b || '').trim() || '180');
  const axes = planeAxes(v.plane);
  const tip = String(v.tip || '').replace(/[\[\]\r\n]/g, '').trim().replace(/^,+|,+$/g, '');
  const style = tip ? tip + ',thick' : 'thick';
  return `\\begin{scope}[shift={${c}}, x={($(${axes[0]})-(0,0,0)$)}, y={($(${axes[1]})-(0,0,0)$)}]\n    \\draw[${style}] (${a0}:${r}) arc (${a0}:${a1}:${r});\n  \\end{scope}`;
}
function atExpr(pt) {
  return pt && pt.ref ? pt.ref : `${+Number(pt[0]).toFixed(3)},${+Number(pt[1]).toFixed(3)}`;
}
function turnArrow(pt, label, a0, a1, rx, ry) {
  const node = String(label || '').trim() ? ` node[midway, above] {${String(label).trim()}}` : '';
  const rad = ry == null ? `radius=${rx}` : `x radius=${rx}, y radius=${ry}`;
  const from = ry == null ? `${a0}:${rx}` : `${a0}:${rx} and ${ry}`;
  return `\\draw[-{Latex[length=2.5mm,width=2mm,flex'=1]}, thick] ($(${atExpr(pt)})+(${from})$) arc[start angle=${a0}, end angle=${a1}, ${rad}]${node};`;
}
function turnAxis(p0, p1, label, a0, a1, rx, ry) {
  const node = String(label || '').trim() ? ` node[midway, above] {${String(label).trim()}}` : '';
  const head = `-{Latex[length=2.5mm,width=2mm,flex'=1]}`;
  const arc = `($(0,0)+(${a0}:${rx} and ${ry})$) arc[start angle=${a0}, end angle=${a1}, x radius=${rx}, y radius=${ry}]${node}`;
  if ((p0 && p0.ref) || (p1 && p1.ref)) {
    return `\\draw[${head}, thick] let \\p1=${P(p0)}, \\p2=${P(p1)}, \\n1={atan2(\\y2-\\y1,\\x2-\\x1)-90} in [shift={({(\\x1+\\x2)/2},{(\\y1+\\y2)/2})}, rotate={\\n1}] ${arc};`;
  }
  const x0 = Number(p0[0]), y0 = Number(p0[1]), x1 = Number(p1[0]), y1 = Number(p1[1]);
  const ang = Math.atan2(y1 - y0, x1 - x0) * 180 / Math.PI - 90;
  const mx = +((x0 + x1) / 2).toFixed(3), my = +((y0 + y1) / 2).toFixed(3), deg = +(Number.isFinite(ang) ? ang : 0).toFixed(3);
  return `\\begin{scope}[shift={(${mx},${my})}, rotate={${deg}}]\n    \\draw[${head}, thick] ${arc};\n  \\end{scope}`;
}
function dimFeet(p1, p2, t, mode) {
  let nx = 0, ny = 1;
  if (mode === 'v') { nx = 1; ny = 0; }
  else if (mode === 'a') {
    const dx = p2[0] - p1[0], dy = p2[1] - p1[1], L = Math.hypot(dx, dy);
    if (L > 1e-6) { nx = -dy / L; ny = dx / L; }
  }
  const foot = p => {
    const k = (t[0] - p[0]) * nx + (t[1] - p[1]) * ny;
    return [p[0] + k * nx, p[1] + k * ny];
  };
  return [foot(p1), foot(p2)];
}
function dimCode(pts, label, v) {
  const mode = v && (v.mode === 'v' || v.mode === 'a') ? v.mode : 'h';
  const arrow = v && v.arrow === 'out' ? 'out' : 'in';
  const id = (v && v.id) || 1;
  const A = 'd' + id + 'a', B = 'd' + id + 'b', T = 'd' + id + 't', C = 'd' + id + 'c', D = 'd' + id + 'd';
  const tip = '>={Stealth[length=2mm, width=2mm]}';
  const [fc, fd] = dimFeet(pts[0], pts[1], pts[2], mode);
  const xy = p => `(${+Number(p[0]).toFixed(4)},${+Number(p[1]).toFixed(4)})`;
  const lines = [
    '\\begin{scope}[thin] % udim',
    `    \\coordinate (${A}) at ${P(pts[0])};`,
    `    \\coordinate (${B}) at ${P(pts[1])};`,
    `    \\coordinate (${T}) at ${P(pts[2])};`,
    `    \\coordinate (${C}) at ${xy(fc)};`,
    `    \\coordinate (${D}) at ${xy(fd)};`
  ];
  lines.push(`    \\pgfpointtransformed{\\pgfpointanchor{${A}}{center}}\\pgfgetlastxy{\\udax}{\\uday}`);
  lines.push(`    \\pgfpointtransformed{\\pgfpointanchor{${B}}{center}}\\pgfgetlastxy{\\udbx}{\\udby}`);
  lines.push(`    \\pgfpointtransformed{\\pgfpointanchor{${C}}{center}}\\pgfgetlastxy{\\udcx}{\\udcy}`);
  lines.push(`    \\pgfpointtransformed{\\pgfpointanchor{${D}}{center}}\\pgfgetlastxy{\\uddx}{\\uddy}`);
  lines.push(`    \\pgfpointtransformed{\\pgfpointanchor{${T}}{center}}\\pgfgetlastxy{\\udtx}{\\udty}`);
  lines.push('    \\begin{scope}');
  lines.push('      \\pgftransformreset');
  lines.push('      \\draw[thin, black!65] ($(\\udax,\\uday)!2pt!(\\udcx,\\udcy)$) -- ($(\\udcx,\\udcy)!-4pt!(\\udax,\\uday)$);');
  lines.push('      \\draw[thin, black!65] ($(\\udbx,\\udby)!2pt!(\\uddx,\\uddy)$) -- ($(\\uddx,\\uddy)!-4pt!(\\udbx,\\udby)$);');
  if (arrow === 'out') {
    lines.push(`      \\draw[->, thin, black, ${tip}] ($(\\udcx,\\udcy)!-10pt!(\\uddx,\\uddy)$) -- (\\udcx,\\udcy);`);
    lines.push(`      \\draw[->, thin, black, ${tip}] ($(\\uddx,\\uddy)!-10pt!(\\udcx,\\udcy)$) -- (\\uddx,\\uddy);`);
    lines.push('      \\draw[thin, black] (\\udcx,\\udcy) -- (\\uddx,\\uddy);');
  } else lines.push(`      \\draw[<->, thin, black, ${tip}] (\\udcx,\\udcy) -- (\\uddx,\\uddy);`);
  lines.push(`      \\node[fill=white, inner sep=1.5pt, font=\\small, transform shape=false, text=black] at (\\udtx,\\udty) {${label}};`);
  lines.push('    \\end{scope}');
  lines.push('  \\end{scope}');
  const head = v && v.prefix ? v.prefix + '\n  ' : '';
  return head + lines.join('\n');
}
function tickList(from, to) {
  let a = Math.round(Number(from)), b = Math.round(Number(to));
  if (!Number.isFinite(a) || !Number.isFinite(b)) return '1,2,3';
  if (a > b) { const t = a; a = b; b = t; }
  const xs = [];
  for (let i = a; i <= b && xs.length < 40; i++) if (i !== 0) xs.push(i);
  return xs.length ? xs.join(',') : '1';
}
const PLACE = {
  text: { name: '文字', btn: 'T 文字', n: 1, field: '文字', def: '标注', build: (p, a, rot) => `\\node[${withRot('font=\\small', rot)}] at ${P(p[0])} {${a}};` },
  wire: { name: '线', btn: '─ 线', n: 2, build: p => `\\draw ${P(p[0])} -- ${P(p[1])};` },
  R: { name: '电阻', btn: 'R', n: 2, field: '标注', def: '$R$', build: (p, a) => `\\draw ${P(p[0])} to[R, l=${a}] ${P(p[1])};` },
  C: { name: '电容', btn: 'C', n: 2, field: '标注', def: '$C$', build: (p, a) => `\\draw ${P(p[0])} to[C, l=${a}] ${P(p[1])};` },
  L: { name: '电感', btn: 'L', n: 2, field: '标注', def: '$L$', build: (p, a) => `\\draw ${P(p[0])} to[L, l=${a}] ${P(p[1])};` },
  V: { name: '电压源', btn: 'V', n: 2, field: '标注', def: '$V$', build: (p, a) => `\\draw ${P(p[0])} to[V, l=${a}] ${P(p[1])};` },
  I: { name: '电流源', btn: 'I', n: 2, field: '标注', def: '$I$', build: (p, a) => `\\draw ${P(p[0])} to[I, l=${a}] ${P(p[1])};` },
  sw: { name: '开关', btn: '开关', n: 2, field: '标注', def: '$S_1$', build: (p, a) => `\\draw ${P(p[0])} to[nos, l=${a}] ${P(p[1])};` },
  D: { name: '二极管', btn: 'D', n: 2, field: '标注', def: '$D$', build: (p, a) => `\\draw ${P(p[0])} to[D*, l=${a}] ${P(p[1])};` },
  zener: bipole('稳压', 'zD', '$D_z$'),
  led: bipole('LED', 'leD', '$LED$'),
  batt: bipole('电池', 'battery1', '$E$'),
  lamp: bipole('灯', 'lamp', ''),
  fuse: bipole('熔断', 'fuse', ''),
  spring: { name: '弹簧', btn: '弹簧', n: 2, field: '标注', def: '$k$', build: (p, a) => `\\draw[decorate,decoration={coil,aspect=0.4,segment length=3mm,amplitude=2.5mm}] ${P(p[0])} -- ${P(p[1])} node[midway,above=4pt]{${a}};` },
  force: { name: '力', btn: '力', n: 2, field: '标注', def: '$F(t)$', build: (p, a) => `\\draw[-{Stealth[length=2.5mm]}, thick] ${P(p[0])} -- ${P(p[1])} node[right]{${a}};` },
  nmos: { name: 'MOS', btn: 'MOS', n: 1, field: '文字', def: 'Q1', build: (p, a, rot) => deviceNode('nmos', p, a, rot, 'Q1') },
  pmos: { name: 'PMOS', btn: 'PMOS', n: 1, field: '文字', def: 'Q3', build: (p, a, rot) => deviceNode('pmos', p, a, rot, 'Q3') },
  npn: { name: '三极管', btn: '三极管', n: 1, field: '文字', def: 'Q2', build: (p, a, rot) => deviceNode('npn', p, a, rot, 'Q2') },
  pnp: { name: 'PNP', btn: 'PNP', n: 1, field: '文字', def: 'Q4', build: (p, a, rot) => deviceNode('pnp', p, a, rot, 'Q4') },
  xfmr: { name: '变压器', btn: '变压器', n: 1, field: '文字', def: 'T1', build: (p, a, rot) => deviceNode('transformer', p, a, rot, 'T1') },
  opamp: { name: '运放', btn: '运放', n: 1, field: '文字', def: 'op', build: (p, a, rot) => deviceNode('op amp', p, a, rot, 'op') },
  buffer: { name: '缓冲', btn: '缓冲', n: 1, field: '文字', def: 'buf', build: (p, a, rot) => deviceNode('buffer', p, a, rot, 'buf') },
  gnd: { name: '接地', btn: '接地', n: 1, build: (p, a, rot) => `\\node[${withRot('ground', rot)}] at ${P(p[0])} {};` },
  dot: { name: '节点', btn: '节点', n: 1, build: (p, a, rot) => `\\node[${withRot('circ', rot)}] at ${P(p[0])} {};` },
  box: { name: '芯片', btn: '芯片', n: 1, field: '文字', def: 'IC', build: (p, a, rot) => `\\node[${withRot('draw, fill=white, minimum width=1.6cm, minimum height=0.8cm', rot)}] (ic) at ${P(p[0])} {${a}};` },
  mass: { name: '质量', btn: '质量', n: 1, field: '文字', def: '$m$', build: (p, a, rot) => `\\node[${withRot('draw, fill=gray!15, minimum width=1.2cm, minimum height=1.2cm', rot)}] (m1) at ${P(p[0])} {${a}};` },
  damper: { name: '阻尼', btn: '阻尼', n: 1, build: (p, a, rot) => placeLocal('\\draw (0,0) -- (0.8,0) (0.8,-0.25) -- (0.8,0.25) (0.6,-0.32) -- (1.2,-0.32) -- (1.2,0.32) -- (0.6,0.32) (1.2,0) -- (2,0);', p[0], rot) },
  wall: { name: '固定壁', btn: '固定壁', n: 1, build: (p, a, rot) => placeLocal('\\fill[pattern=north east lines] (-0.2,-0.8) rectangle (0,0.8); \\draw[thick] (0,-0.8) -- (0,0.8);', p[0], rot) }
};
Object.keys(PLACE).forEach(k => { if (!PLACE[k].panel) PLACE[k].panel = 'circuit'; });
Object.assign(PLACE, {
  btext: { panel: 'block', name: '文字', btn: 'T 文字', n: 1, field: '文字', def: '说明', build: (p, a, rot) => `\\node[${withRot('font=\\small', rot)}] at ${P(p[0])} {${a}};` },
  bbox: { panel: 'block', name: '方框', btn: '方框', n: 1, field: '文字', def: '模块', build: (p, a, rot) => `\\node[${withRot('draw, minimum width=1.8cm, minimum height=0.8cm', rot)}] at ${P(p[0])} {${a}};` },
  barrow: { panel: 'block', name: '箭头', btn: '箭头', n: 2, build: p => `\\draw[->] ${P(p[0])} -- ${P(p[1])};` },
  bround: { panel: 'block', name: '圆角', btn: '圆角', n: 1, field: '文字', def: '处理', build: (p, a, rot) => `\\node[${withRot('draw, rounded corners, minimum width=1.8cm, minimum height=0.8cm', rot)}] at ${P(p[0])} {${a}};` },
  bdiamond: { panel: 'block', name: '判断', btn: '判断', n: 1, field: '文字', def: '条件', build: (p, a, rot) => `\\node[${withRot('draw, diamond, aspect=1.8, inner sep=1pt', rot)}] at ${P(p[0])} {${a}};` },
  bellipse: { panel: 'block', name: '椭圆', btn: '椭圆', n: 1, field: '文字', def: '起止', build: (p, a, rot) => `\\node[${withRot('draw, ellipse', rot)}] at ${P(p[0])} {${a}};` },
  pfn: { panel: 'plot', name: '函数', btn: '函数', n: 0, inputs: [{ id: 'expr', label: '式', def: 'x', wide: true }, { id: 'a', label: '从', def: '0' }, { id: 'b', label: '到', def: '6' }], build: (p, a, rot, v) => `\\addplot[blue, thick, domain=${v.a}:${v.b}, samples=80] {${v.expr}};` },
  pmarks: { panel: 'plot', name: '散点', btn: '散点', n: 0, inputs: [{ id: 'pts', label: '点', def: '(0,1) (1,2) (2,1.5) (3,2.4)', wide: true }], build: (p, a, rot, v) => `\\addplot[only marks, mark=*] coordinates {${v.pts}};` },
  plabel: { panel: 'plot', name: '标注', btn: '标注', n: 0, inputs: [{ id: 't', label: '文字', def: '标注', wide: true }, { id: 'x', label: 'X', def: '2' }, { id: 'y', label: 'Y', def: '2' }], build: (p, a, rot, v) => `\\node[font=\\small, anchor=south west] at (axis cs:${v.x},${v.y}) {${v.t}};` },
  pbar: { panel: 'plot', name: '柱状', btn: '柱状', n: 0, inputs: [{ id: 'pts', label: '点', def: '(1,2) (2,3) (3,1.4)', wide: true }], build: (p, a, rot, v) => `\\addplot[ybar, bar width=8pt, fill=blue!35] coordinates {${v.pts}};` },
  pstep: { panel: 'plot', name: '阶梯', btn: '阶梯', n: 0, inputs: [{ id: 'pts', label: '点', def: '(0,0) (1,1) (2,1) (3,2)', wide: true }], build: (p, a, rot, v) => `\\addplot[const plot, thick] coordinates {${v.pts}};` },
  psmooth: { panel: 'plot', name: '平滑', btn: '平滑', n: 0, inputs: [{ id: 'pts', label: '点', def: '(0,0) (1,1.2) (2,0.4) (3,1.6)', wide: true }], build: (p, a, rot, v) => `\\addplot[smooth, thick] coordinates {${v.pts}};` },
  parea: { panel: 'plot', name: '面积', btn: '面积', n: 0, inputs: [{ id: 'expr', label: '式', def: 'x', wide: true }, { id: 'a', label: '从', def: '0' }, { id: 'b', label: '到', def: '4' }], build: (p, a, rot, v) => `\\addplot[blue!30, fill, domain=${v.a}:${v.b}, samples=40] {${v.expr}} \\closedcycle;` },
  pvline: { panel: 'plot', name: '竖线', btn: '竖线', n: 0, inputs: [{ id: 'x', label: 'X', def: '3' }], build: (p, a, rot, v) => `\\draw[dashed] (axis cs:${v.x},\\pgfkeysvalueof{/pgfplots/ymin}) -- (axis cs:${v.x},\\pgfkeysvalueof{/pgfplots/ymax});` },
  pline: { panel: 'plot', name: '折线', btn: '折线', n: 0, inputs: [{ id: 'pts', label: '点', def: '(0,0) (1,1) (2,0.4) (3,1.2)', wide: true }], build: (p, a, rot, v) => `\\addplot[thick] coordinates {${v.pts}};` },
  gline: { panel: 'any', hideOn: ['circuit'], name: '直线', btn: '直线', n: 2, build: p => `\\draw ${P(p[0])} -- ${P(p[1])};` },
  gtext: { panel: 'any', hideOn: ['circuit', 'block'], name: '文字', btn: '文字', n: 1, field: '文字', def: '文字', build: (p, a, rot) => `\\node[${withRot('font=\\small', rot)}] at ${P(p[0])} {${a}};` },
  garrow: { panel: 'any', hideOn: ['block'], name: '箭头', btn: '箭头', n: 2, build: p => `\\draw[->] ${P(p[0])} -- ${P(p[1])};` },
  gboth: { panel: 'any', name: '双向', btn: '双向', n: 2, build: p => `\\draw[<->] ${P(p[0])} -- ${P(p[1])};` },
  gdash: { panel: 'any', name: '虚线', btn: '虚线', n: 2, build: p => `\\draw[dashed] ${P(p[0])} -- ${P(p[1])};` },
  gthick: { panel: 'any', name: '粗线', btn: '粗线', n: 2, build: p => `\\draw[thick] ${P(p[0])} -- ${P(p[1])};` },
  gbend: { panel: 'any', name: '弯曲', btn: '弯曲', n: 2, build: p => `\\draw ${P(p[0])} to[bend left=25] ${P(p[1])};` },
  grect: { panel: 'any', name: '矩形', btn: '矩形', n: 2, build: p => `\\draw ${P(p[0])} rectangle ${P(p[1])};` },
  gfill: { panel: 'any', name: '填充', btn: '填充', n: 2, build: p => `\\fill[blue!20] ${P(p[0])} rectangle ${P(p[1])};` },
  ggrid: { panel: 'any', name: '网格', btn: '网格', n: 2, build: p => `\\draw[step=0.5cm, gray!55] ${P(p[0])} grid ${P(p[1])};` },
  gbrace: { panel: 'any', name: '花括号', btn: '花括号', n: 2, build: p => `\\draw[decorate,decoration={brace,amplitude=5pt}] ${P(p[0])} -- ${P(p[1])};` },
  gcirc: { panel: 'any', name: '圆', btn: '圆', n: 1, rot: false, inputs: [{ id: 'r', label: '半径', def: '0.4' }], build: (p, a, rot, v) => `\\draw ${P(p[0])} circle (${v.r});` },
  gfillc: { panel: 'any', name: '实心圆', btn: '实心圆', n: 1, rot: false, inputs: [{ id: 'r', label: '半径', def: '0.15' }], build: (p, a, rot, v) => `\\fill ${P(p[0])} circle (${v.r});` },
  gell: { panel: 'any', name: '椭圆', btn: '椭圆', n: 1, rot: false, inputs: [{ id: 'x', label: '横', def: '0.6' }, { id: 'y', label: '纵', def: '0.35' }], build: (p, a, rot, v) => `\\draw ${P(p[0])} ellipse (${v.x} and ${v.y});` },
  garc: { panel: 'any', name: '弧', btn: '弧', n: 1, rot: false, inputs: [{ id: 'a', label: '起', def: '0' }, { id: 'b', label: '终', def: '90' }, { id: 'r', label: '半径', def: '0.6' }], build: (p, a, rot, v) => `\\draw ${P(p[0])} arc (${v.a}:${v.b}:${v.r});` },
  gcoord: { panel: 'any', name: '坐标', btn: '坐标', n: 1, rot: false, field: '名称', def: 'p', build: (p, a) => `\\coordinate (${a || 'p'}) at ${P(p[0])};` },
  bcyl: { panel: 'block', name: '圆柱', btn: '圆柱', n: 1, field: '文字', def: '', build: (p, a, rot) => `\\node[${withRot('draw, cylinder, shape border rotate=90, minimum height=1.1cm, minimum width=0.7cm', rot)}] at ${P(p[0])} {${a}};` },
  btrap: { panel: 'block', name: '梯形', btn: '梯形', n: 1, field: '文字', def: '', build: (p, a, rot) => `\\node[${withRot('draw, trapezium, trapezium stretches=true, minimum width=1.6cm, minimum height=0.8cm', rot)}] at ${P(p[0])} {${a}};` },
  meter: { panel: 'circuit', name: '电流表', btn: '电流表', n: 2, field: '标注', def: 'A', build: (p, a) => `\\draw ${P(p[0])} to[rmeter, t=${a || 'A'}] ${P(p[1])};` },
  open: { panel: 'circuit', name: '开路', btn: '开路', n: 2, build: p => `\\draw ${P(p[0])} to[open] ${P(p[1])};` },
  xpt: { panel: 'plane', name: '点', btn: '点', n: 1, rot: false, field: '文字', def: '$A$', build: planePoint },
  xseg: { panel: 'plane', name: '线段', btn: '线段', n: 2, field: '标注', def: '线段', build: (p, a) => `\\draw[blue, thick] ${P(p[0])} -- ${P(p[1])}${a ? ` node[midway, above left] {${a}}` : ''};` },
  xfn: { panel: 'plane', name: '函数', btn: '函数', n: 0, inputs: [{ id: 'expr', label: '式', def: '0.5*\\x*\\x - 1', wide: true }, { id: 'a', label: '从', def: '-2.8' }, { id: 'b', label: '到', def: '2.8' }], build: (p, a, rot, v) => `\\draw[domain=${v.a}:${v.b}, smooth, variable=\\x, red, thick] plot ({\\x}, {${v.expr}});` },
  xaxes: { panel: 'plane', name: '坐标轴', btn: '坐标轴', n: 0, inputs: [{ id: 'x0', label: 'x起', def: '-4' }, { id: 'x1', label: 'x止', def: '5' }, { id: 'y0', label: 'y起', def: '-3' }, { id: 'y1', label: 'y止', def: '5' }], build: (p, a, rot, v) => `\\draw[->, thick] (${v.x0},0) -- (${v.x1},0) node[right] {$x$};\n  \\draw[->, thick] (0,${v.y0}) -- (0,${v.y1}) node[above] {$y$};` },
  xticks: { panel: 'plane', name: '刻度', btn: '刻度', n: 0, inputs: [{ id: 'x0', label: 'x起', def: '-3' }, { id: 'x1', label: 'x止', def: '4' }, { id: 'y0', label: 'y起', def: '-2' }, { id: 'y1', label: 'y止', def: '4' }], build: (p, a, rot, v) => `\\foreach \\x in {${tickList(v.x0, v.x1)}}\n    \\draw (\\x, 0.05) -- (\\x, -0.05) node[below, font=\\small] {\\x};\n  \\foreach \\y in {${tickList(v.y0, v.y1)}}\n    \\draw (0.05, \\y) -- (-0.05, \\y) node[left, font=\\small] {\\y};` },
  rot2: { panel: 'any', name: '二维回转箭头', btn: '二维回转', n: 1, rot: false, field: '标注', def: '$\\omega$', inputs: [{ id: 'a', label: '起', def: '40' }, { id: 'b', label: '终', def: '320' }, { id: 'r', label: '半径', def: '0.7' }], build: (p, a, rot, v) => turnArrow(p[0], a, numOr(v.a, 40), numOr(v.b, 320), numOr(v.r, 0.7)) },
  rot3: { panel: 'any', name: '三维回转箭头', btn: '三维回转', n: 2, field: '标注', def: '$\\omega$', inputs: [{ id: 'a', label: '起', def: '40' }, { id: 'b', label: '终', def: '320' }, { id: 'rx', label: '垂直', def: '0.8' }, { id: 'ry', label: '轴向', def: '0.32' }], build: (p, a, rot, v) => turnAxis(p[0], p[1], a, numOr(v.a, 40), numOr(v.b, 320), numOr(v.rx, 0.8), numOr(v.ry, 0.32)) },
  ax2: { panel: 'any', name: '二维坐标系', btn: '二维坐标', n: 1, inputs: [{ id: 'lx', label: 'x长', def: '1.6' }, { id: 'ly', label: 'y长', def: '1.6' }], build: (p, a, rot, v) => relAxes(p[0], rot, [`\\draw[->,thick] __at__ --++ (${numOr(v.lx, 1.6)},0) node[anchor=west,xshift=1pt] {$x$};`, `\\draw[->,thick] __at__ --++ (0,${numOr(v.ly, 1.6)}) node[anchor=south,yshift=1pt] {$y$};`]) },
  ax3: { panel: 'any', name: '三维坐标系', btn: '三维坐标', n: 1, inputs: [{ id: 'lx', label: 'x长', def: '1.2' }, { id: 'ly', label: 'y长', def: '1.6' }, { id: 'lz', label: 'z长', def: '1.6' }], build: (p, a, rot, v) => relAxes(p[0], rot, [`\\draw[->,thick] __at__ --++ (${numOr(v.lx, 1.2)},0,0) node[anchor=north,yshift=-3pt] {$x$};`, `\\draw[->,thick] __at__ --++ (0,${numOr(v.ly, 1.6)},0) node[anchor=south,yshift=1pt] {$y$};`, `\\draw[->,thick] __at__ --++ (0,0,${numOr(v.lz, 1.6)}) node[anchor=north,yshift=-4pt] {$z$};`]) },
  sline: { panel: 'space', name: '三维线段', btn: '三维线段', n: 0, inputs: [{ id: 'pts', label: '坐标', def: '(0,0,0) -- (1,1,1)', wide: 'path' }], build: (p, a, rot, v) => `\\draw[thick] ${spacePath(v.pts)};` },
  sarrow: { panel: 'space', name: '三维箭头', btn: '三维箭头', n: 0, inputs: [{ id: 'pts', label: '坐标', def: '(0,0,0) -- (1,1,1)', wide: 'path' }], build: (p, a, rot, v) => `\\draw[->,thick] ${spacePath(v.pts)};` },
  scirc: { panel: 'space', name: '三维圆', btn: '三维圆', n: 0, inputs: [{ id: 'c', label: '圆心', def: '(0,0,0)', wide: true }, { id: 'r', label: '半径', def: '0.5' }, { id: 'plane', label: '平面', def: 'xy', wide: 'path' }, { id: 'tip', label: '线', def: '' }], build: (p, a, rot, v) => arc3(v, true) },
  sarc: { panel: 'space', name: '三维弧', btn: '三维弧', n: 0, inputs: [{ id: 'c', label: '圆心', def: '(0,0,0)', wide: true }, { id: 'r', label: '半径', def: '0.5' }, { id: 'a', label: '起', def: '20' }, { id: 'b', label: '终', def: '200' }, { id: 'plane', label: '平面', def: 'xy', wide: 'path' }, { id: 'tip', label: '线', def: '->' }], build: (p, a, rot, v) => arc3(v, false) },
  dim: { panel: 'any', dim: true, name: '尺寸', btn: '尺寸', n: 3, field: '文字', def: '', build: (p, a, rot, v) => dimCode(p, a, v) }
});
const FIXED = ['rot2', 'rot3', 'ax2', 'ax3'];
const SHOWN_COMMON = ['gline', 'gtext', 'garrow', 'grect', 'gcirc', 'gfill', 'gell', 'garc', 'gdash', 'ggrid'];
const PANELS = {
  circuit: { title: '电路', core: ['text', 'wire', 'R', 'C', 'L', 'V', 'I', 'sw', 'dim'], lib: ['D', 'nmos', 'npn', 'xfmr', 'opamp', 'gnd', 'dot', 'box', 'spring', 'damper', 'mass', 'wall', 'force'] },
  block: { title: '框图', core: ['btext', 'bbox', 'barrow', 'dim'], lib: ['bround', 'bdiamond', 'bellipse'] },
  plot: { title: '曲线', core: ['pfn', 'pmarks', 'plabel', 'dim'], lib: ['pbar', 'pstep', 'psmooth', 'parea', 'pvline'] },
  plane: { title: '二维', core: ['xpt', 'xseg', 'xfn', 'dim'], lib: ['xaxes', 'xticks'] },
  space: { title: '三维', core: ['sline', 'sarrow', 'scirc', 'sarc', 'dim'], lib: [] }
};
function visibleCommon(name) {
  return SHOWN_COMMON.filter(k => !((PLACE[k].hideOn || []).includes(name)));
}
function inPanel(k, name) {
  const p = PLACE[k];
  if (!p || FIXED.includes(k) || PANELS[name].core.includes(k) || (p.hideOn || []).includes(name)) return false;
  return p.panel === name || p.panel === 'any';
}
function pictureKind(code) {
  const s = String(code || '');
  if (/\\begin\s*\{axis\}/.test(s) || /\\addplot\b/.test(s)) return 'plot';
  if (/\\begin\s*\{circuitikz\}/.test(s)) return 'circuit';
  if (/\\tdplotsetmaincoords|tdplot_main_coords|\\tdplotsetcoord/.test(s)) return 'space';
  if (/\\begin\s*\{tikzpicture\}/.test(s)) {
    if (/node\s*\[[^\]]*\]\s*\{\s*\$[xy]\$\s*\}/.test(s) || /plot\s*\(\s*\{\s*\\x\s*\}/.test(s) || /plot\s*\(\s*\\x\b/.test(s) || /\\foreach\s+\\[xy]\b/.test(s)) return 'plane';
    return 'block';
  }
  return '';
}
function fillTpl(tpl, pts, a, rot) {
  return String(tpl)
    .replaceAll('{{1}}', P(pts[0]))
    .replaceAll('{{2}}', pts[1] ? P(pts[1]) : '')
    .replaceAll('{{文字}}', a == null ? '' : String(a))
    .replaceAll('{{角度}}', String(Number(rot) || 0));
}

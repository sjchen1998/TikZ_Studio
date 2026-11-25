;;; ====================================================================
;;; LoadXData.lsp — AutoCAD 梁 + 板壳：截面/属性 / 载荷 / 约束 XData + 可视化
;;; 图层：CAE_VIS_LOAD / CAE_VIS_BC / CAE_VIS_SEC / CAE_VIS_WELD
;;; 语言：*CAE_LANG* ("ZH"|"EN") + SETLANG
;;; 默认单位：分布力/线载荷 N-mm、集中力 N、面压 MPa；线刚度 N-mm、角刚度 Nmm/rad
;;; ====================================================================

;;; ---------- 全局显示比例 ----------
(if (not *CAE_SCALE_LOAD*) (setq *CAE_SCALE_LOAD* 1.0))
(if (not *CAE_SCALE_BC*)   (setq *CAE_SCALE_BC*   1.0))
(if (not *CAE_SCALE_SEC*)  (setq *CAE_SCALE_SEC*  1.0))
(if (not (boundp '*cae-vis-batch*)) (setq *cae-vis-batch* nil))

;;; ---------- 语言：*CAE_LANG* = "ZH" | "EN"；命令 SETLANG 一键切换 ----------
(if (not *CAE_LANG*) (setq *CAE_LANG* "ZH"))

;;; (_T 中文提示 英文提示) — 中文界面仍保留必要英文单位
(defun _T (zh en)
  (if (= (strcase (if *CAE_LANG* *CAE_LANG* "ZH")) "EN") en zh)
)

(defun c:SETLANG ()
  (if (= (strcase *CAE_LANG*) "EN")
    (progn
      (setq *CAE_LANG* "ZH")
      (princ (_T "\n[语言] 已切换为纯中文提示（必要英文单位仍保留）。"
                 "\n[Lang] Switched to Chinese prompts."))
    )
    (progn
      (setq *CAE_LANG* "EN")
      (princ (_T "\n[语言] 已切换为纯英文提示。"
                 "\n[Lang] Switched to English prompts."))
    )
  )
  (princ)
)

;;; 分布/线载荷单位：N-mm（即 N/mm）、kN-m（即 kN/m）；[] 内不能写 /
(defun ask-dist-unit (/ u)
  (initget "N-mm kN-m")
  (setq u (getkword (_T "\n单位 [N-mm/kN-m] <N-mm>: "
                        "\nUnit [N-mm/kN-m] <N-mm>: ")))
  (if (not u) (setq u "N-mm"))
  u
)

;;; 旧单位串规范化：N/mm、Nmm → N-mm；kN/m → kN-m
(defun normalize-dist-unit (unitStr)
  (cond
    ((or (not unitStr) (/= (type unitStr) 'STR) (= unitStr "")
         (= unitStr "N/mm") (= unitStr "Nmm")) "N-mm")
    ((= unitStr "kN/m") "kN-m")
    ((= unitStr "kNm") "kN-m")
    (T unitStr)
  )
)

(defun ask-force-unit (/ u)
  (initget "N kN")
  (setq u (getkword (_T "\n单位 [N/kN] <N>: "
                        "\nUnit [N/kN] <N>: ")))
  (if (not u) (setq u "N"))
  u
)

;;; 集中弯矩单位：Nmm (=N·mm)、Nm、kNm；[] 内不能写 ·
(defun ask-moment-unit (/ u)
  (initget "Nmm Nm kNm")
  (setq u (getkword (_T "\n单位 [Nmm/Nm/kNm] <Nmm>: "
                        "\nUnit [Nmm/Nm/kNm] <Nmm>: ")))
  (if (not u) (setq u "Nmm"))
  u
)

(defun ask-pressure-unit (/ u)
  (initget "MPa kPa")
  (setq u (getkword (_T "\n单位 [MPa/kPa] <MPa>: "
                        "\nUnit [MPa/kPa] <MPa>: ")))
  (if (not u) (setq u "MPa"))
  u
)

;;; 线刚度单位：N-mm（即 N/mm）、kN-m（即 kN/m）；[] 内不能写 /
(defun ask-trans-k-unit (/ u)
  (initget "N-mm kN-m")
  (setq u (getkword (_T "\n单位 [N-mm/kN-m] <N-mm>: "
                        "\nUnit [N-mm/kN-m] <N-mm>: ")))
  (if (not u) (setq u "N-mm"))
  u
)

;;; 角刚度单位：Nmm/rad、Nm/rad（菜单用 Nmm-rad/Nm-rad）
(defun ask-rot-k-unit (/ u)
  (initget "Nmm-rad Nm-rad")
  (setq u (getkword (_T "\n单位 [Nmm-rad/Nm-rad] <Nmm-rad>: "
                        "\nUnit [Nmm-rad/Nm-rad] <Nmm-rad>: ")))
  (if (not u) (setq u "Nmm-rad"))
  (if (= u "Nm-rad") "Nm/rad" "Nmm/rad")
)

;;; ---------- APPID ----------
(defun cae-regapp (name)
  (if (not (tblsearch "APPID" name)) (regapp name))
)
(defun register-all-cae-apps ()
  (if *cae-vis-batch* (cae-vis-end-batch))
  (foreach a '("MY_CAE_LOAD" "MY_CAE_POINT_LOAD" "MY_CAE_MOMENT" "MY_CAE_BC"
               "MY_CAE_COMP_BC" "MY_CAE_SPRING" "MY_CAE_SEC"
               "MY_CAE_MEMBER_KIND"
               "MY_CAE_SHELL_LOAD" "MY_CAE_SHELL_PROP"
               "MY_CAE_SHELL_GEOM" "MY_CAE_SHELL_BC"
               "MY_CAE_SPOT_WELD" "MY_CAE_SEAM_WELD")
    (cae-regapp a)
  )
)

;;; 构件类型 MY_CAE_MEMBER_KIND：1000=BEAM|ROD（缺省=BEAM）；仅 LINE
(defun cae-member-kind (ent / ed xd app tag)
  (setq ed (entget ent '("MY_CAE_MEMBER_KIND")))
  (setq xd (assoc -3 ed))
  (if xd
    (progn
      (setq app (cdr (cadr xd)) tag nil)
      (foreach p app
        (if (and (= (car p) 1000) (not tag))
          (setq tag (strcase (cdr p)))
        )
      )
      (if (member tag '("ROD" "BEAM")) tag "BEAM")
    )
    "BEAM"
  )
)

(defun cae-is-rod (ent)
  (= (cae-member-kind ent) "ROD")
)
(defun register-shell-load-app () (cae-regapp "MY_CAE_SHELL_LOAD"))
(defun register-shell-prop-app ()
  (cae-regapp "MY_CAE_SHELL_PROP")
  (cae-regapp "MY_CAE_SHELL_GEOM")
)
(defun register-shell-bc-app () (cae-regapp "MY_CAE_SHELL_BC"))
;;; 板壳代码中的 lock-all / unlock-all 映射到统一图层函数
(defun lock-all-cae-layers () (lock-vis-layer))
(defun unlock-all-cae-layers () (unlock-vis-layer))

;;; ---------- 板壳实体类型（含 EXTRUDEDSURFACE 等现代曲面）----------
;;; DXF 0：经典 SURFACE/REGION + EXTRUDED/PLANED/LOFTED/REVOLVED/SWEPT/NURBS
(defun cae-shell-type-filter ()
  "MESH,REGION,SURFACE,EXTRUDEDSURFACE,PLANESURFACE,LOFTEDSURFACE,REVOLVEDSURFACE,SWEPTSURFACE,NURBSSURFACE,3DSOLID,BODY,3DFACE,LWPOLYLINE"
)
(defun cae-shell-type-filter-ins ()
  (strcat (cae-shell-type-filter) ",INSERT")
)
(defun cae-shell-type-p (eType)
  (or (and eType (= (type eType) 'STR) (wcmatch eType "*SURFACE"))
      (member eType '("MESH" "REGION" "3DSOLID" "BODY" "3DFACE" "LWPOLYLINE")))
)
;;; 真正的板：曲面/面域，或闭合多段线。回转母线等开口 LWPOLYLINE 不是板。
(defun cae-shell-plate-p (ent / ed et flags)
  (setq ed (entget ent)
        et (cdr (assoc 0 ed)))
  (cond
    ((= et "LWPOLYLINE")
      (setq flags (if (assoc 70 ed) (cdr (assoc 70 ed)) 0))
      (= 1 (logand flags 1)))
    (T (cae-shell-type-p et))
  )
)
;;; 删掉该实体上已有的板厚符号，并清空厚度/偏置（覆盖前调用，避免残留）
(defun cae-clear-shell-prop (ent / ed oldXd appData oldBlk)
  (setq ed (entget ent '("MY_CAE_SHELL_PROP"))
        oldXd (assoc -3 ed))
  (if oldXd
    (progn
      (setq appData (cdr (cadr oldXd)))
      (if (and (> (length appData) 4)
               (setq oldBlk (handent (cdr (nth 4 appData))))
               (entget oldBlk))
        (progn (cae-vis-unlock) (entdel oldBlk) (cae-vis-lock))
      )
      (entmod (append (entget ent) '((-3 ("MY_CAE_SHELL_PROP")))))
      (entmod (append (entget ent) '((-3 ("MY_CAE_SHELL_GEOM")))))
      (entupd ent)
    )
  )
)
;;; 现代曲面族（炸开时常先变成 REGION / 边线）
(defun cae-modern-surface-p (eType)
  (or (= eType "SURFACE")
      (and eType (= (type eType) 'STR) (wcmatch eType "*SURFACE")))
)

;;; AutoLISP 无 Common Lisp SUBSEQ；end 为开区间，nil=到末尾
(defun cae-subseq (lst start end / i out)
  (if (not end) (setq end (length lst)))
  (setq i 0 out nil)
  (foreach x lst
    (if (and (>= i start) (< i end))
      (setq out (append out (list x)))
    )
    (setq i (1+ i))
  )
  out
)


;;; ---------- 图层（四图层 + 兼容旧 CAE_LOAD_VIS）----------
;;; CAE_VIS_LOAD=红(1) / CAE_VIS_BC=青(4) / CAE_VIS_SEC=品红(6) / CAE_VIS_WELD=黄(2)
;;; 用 entmake/entmod 静默处理，避免 command -LAYER 刷屏（批量设截面时极慢）
;;; DXF 70 bit2(=4)=锁定；62 负值=图层关闭
(defun cae-ensure-layer (name color / en ed curCol)
  (setq en (tblobjname "LAYER" name))
  (if (null en)
    (progn
      (entmake (list '(0 . "LAYER") (cons 2 name) '(70 . 0)
                     (cons 62 (abs color)) '(6 . "Continuous")))
      (setq en (tblobjname "LAYER" name))
    )
  )
  (if en
    (progn
      (setq ed (entget en) curCol (cdr (assoc 62 ed)))
      ;; 校正颜色，保留开/关状态
      (if (/= (abs curCol) (abs color))
        (progn
          (setq ed (subst (cons 62 (if (< curCol 0) (- (abs color)) (abs color)))
                          (assoc 62 ed) ed))
          (entmod ed)
        )
      )
    )
  )
  en
)
(defun cae-set-layer-lock (name locked / en ed flags)
  (setq en (tblobjname "LAYER" name))
  (if en
    (progn
      (setq ed (entget en) flags (cdr (assoc 70 ed)))
      (setq flags (if locked (logior flags 4) (logand flags (~ 4))))
      (if (/= flags (cdr (assoc 70 ed)))
        (entmod (subst (cons 70 flags) (assoc 70 ed) ed))
      )
    )
  )
)
(defun lock-vis-layer (/ layInfo)
  (setq layInfo '(("CAE_VIS_LOAD" . 1) ("CAE_VIS_BC" . 4) ("CAE_VIS_SEC" . 6)
                  ("CAE_VIS_WELD" . 2)))
  (foreach item layInfo
    (cae-ensure-layer (car item) (cdr item))
    (cae-set-layer-lock (car item) T)
  )
)
(defun unlock-vis-layer ()
  (foreach lay '("CAE_VIS_LOAD" "CAE_VIS_BC" "CAE_VIS_SEC" "CAE_VIS_WELD" "CAE_LOAD_VIS")
    (cae-set-layer-lock lay nil)
  )
)
;;; 批量写实体时：外层 begin/end 各锁一次；内层 create/remove 跳过重复 lock
;;; Esc 中断后若 batch 残留，下次 register / begin 会自动收尾
(defun cae-vis-end-batch ()
  (setq *cae-vis-batch* nil)
  (lock-vis-layer)
)
(defun cae-vis-begin-batch ()
  (if *cae-vis-batch* (cae-vis-end-batch))
  (setq *cae-vis-batch* T)
  (unlock-vis-layer)
)
(defun cae-vis-unlock () (if (not *cae-vis-batch*) (unlock-vis-layer)))
(defun cae-vis-lock () (if (not *cae-vis-batch*) (lock-vis-layer)))

;;; ---------- 向量 ----------
(defun vec-unit (v / len)
  (setq len (sqrt (+ (* (car v) (car v)) (* (cadr v) (cadr v)) (* (caddr v) (caddr v)))))
  (if (> len 1e-9)
    (list (/ (car v) len) (/ (cadr v) len) (/ (caddr v) len))
    nil
  )
)
(defun vec-scale (v s) (list (* (car v) s) (* (cadr v) s) (* (caddr v) s)))
(defun vec-add (v1 v2) (mapcar '+ v1 v2))
(defun vec-sub (v1 v2) (mapcar '- v1 v2))
(defun vec-cross (v1 v2)
  (list
    (- (* (cadr v1) (caddr v2)) (* (caddr v1) (cadr v2)))
    (- (* (caddr v1) (car v2)) (* (car v1) (caddr v2)))
    (- (* (car v1) (cadr v2)) (* (cadr v1) (car v2)))
  )
)
(defun vec-dot (v1 v2)
  (+ (* (car v1) (car v2)) (* (cadr v1) (cadr v2)) (* (caddr v1) (caddr v2)))
)

;;; 由主轴 e1 构造右手正交基 (e1 e2 e3)
(defun make-local-basis (e1 / refVec e2 e3)
  (if (< (abs (car e1)) 0.9)
    (setq refVec '(1.0 0.0 0.0))
    (setq refVec '(0.0 1.0 0.0))
  )
  (setq e2 (vec-unit (vec-cross refVec e1)))
  (setq e3 (vec-unit (vec-cross e1 e2)))
  (list e1 e2 e3)
)

;;; 点到直线 (p1->p2) 的垂向单位向量
(defun get-perp-unit-vec (p1 p2 pt / ex v)
  (setq ex (vec-unit (vec-sub p2 p1)))
  (if ex
    (progn
      (setq v (vec-sub pt p1))
      (vec-unit (vec-sub v (vec-scale ex (vec-dot v ex))))
    )
    nil
  )
)

;;; 交互：取单位方向向量（Vector 输入 / Pick 两点）
(defun ask-unit-vec (/ inputMode vecInput pStart pEnd)
  (initget "Vector Pick")
  (setq inputMode (getkword (_T "\n方向 Vector=向量, Pick=两点 [Vector/Pick] <Vector>: "
                                "\nDirection Vector=XYZ vector, Pick=two points [Vector/Pick] <Vector>: ")))
  (if (not inputMode) (setq inputMode "Vector"))
  (if (= inputMode "Vector")
    (progn
      (setq vecInput (getpoint (_T "\n全局方向向量 X,Y,Z <0,0,-1>: "
                                   "\nGlobal direction vector X,Y,Z <0,0,-1>: ")))
      (if (not vecInput) (setq vecInput '(0.0 0.0 -1.0)))
      (vec-unit vecInput)
    )
    (progn
      (setq pStart (getpoint (_T "\n方向起点: " "\nDirection start point: ")))
      (if pStart (setq pEnd (getpoint pStart (_T "\n方向终点: " "\nDirection end point: "))))
      (if (and pStart pEnd)
        (vec-unit (mapcar '- (trans pEnd 1 0) (trans pStart 1 0)))
        nil
      )
    )
  )
)

;;; 选梁后捕捉端点 → (list ptNode endTag) 或 nil
(defun pick-beam-end (ent / entData p1 p2 pickPt)
  (setq entData (entget ent))
  (setq p1 (cdr (assoc 10 entData)) p2 (cdr (assoc 11 entData)))
  (setq pickPt (getpoint (_T "\n请捕捉端点 (起点或终点): " "\nPick an endpoint (start or end): ")))
  (if pickPt
    (progn
      (setq pickPt (trans pickPt 1 0))
      (if (<= (distance pickPt p1) (distance pickPt p2))
        (list p1 "START")
        (list p2 "END")
      )
    )
    nil
  )
)

;;; 从端点记录列表中去掉 targetEndTag 一组（每组 stride 项）
(defun xdata-drop-end (appData targetEndTag stride / i j newRecords)
  (setq newRecords nil i 0)
  (while (< i (length appData))
    (if (/= (cdr (nth i appData)) targetEndTag)
      (progn
        (setq j 0)
        (while (< j stride)
          (setq newRecords (append newRecords (list (nth (+ i j) appData))))
          (setq j (1+ j))
        )
      )
    )
    (setq i (+ i stride))
  )
  newRecords
)

;;; 集中力 XData 步长：新版 5（含单位），旧版 4（无单位字段）
(defun ptload-stride (appData / n fifth)
  (setq n (length appData))
  (cond
    ((= n 0) 5)
    ((= (rem n 5) 0)
     (setq fifth (cdr (nth 4 appData)))
     (if (and (= (type fifth) 'STR) (/= fifth "START") (/= fifth "END")) 5 4)
    )
    ((= (rem n 4) 0) 4)
    (T 5)
  )
)

;;; ====================================================================
;;; 分布载荷  MY_CAE_LOAD
;;; ====================================================================
(defun create-load-block (ent loadMag unitVec unitStr / entData p1 p2 beamVec beamLen arrowLen tipR
                               numArrows i tRatio ptOnBeam tip ptTail ptTail1 ptTail2
                               labelPt labelStr blkDefName blkRef)
  (unlock-vis-layer)
  (setq entData (entget ent))
  (setq p1 (cdr (assoc 10 entData)) p2 (cdr (assoc 11 entData)))
  (setq beamVec (vec-sub p2 p1) beamLen (distance p1 p2))
  (setq arrowLen (* beamLen 0.12))
  (if (< arrowLen 100.0) (setq arrowLen 100.0))
  (setq arrowLen (* arrowLen *CAE_SCALE_LOAD*))
  (setq tipR (* arrowLen 0.08))
  (entmake (list '(0 . "BLOCK") '(2 . "*U") '(70 . 1) '(10 0.0 0.0 0.0)))
  ;; 与 K/KR/BC 相同：沿载荷方向缩回一圆半径，尖端落在圆周，不压梁
  (setq ptTail1 (vec-sub '(0.0 0.0 0.0) (vec-scale unitVec arrowLen)))
  (setq ptTail2 (vec-sub beamVec (vec-scale unitVec arrowLen)))
  (entmake (list '(0 . "LINE") '(8 . "0") '(62 . 1) (cons 10 ptTail1) (cons 11 ptTail2)))
  (setq numArrows 5 i 0)
  (while (< i numArrows)
    (setq tRatio (/ (float i) (float (1- numArrows))))
    (setq ptOnBeam (vec-scale beamVec tRatio))
    (setq tip (vec-sub ptOnBeam (vec-scale unitVec tipR)))
    (setq ptTail (vec-sub ptOnBeam (vec-scale unitVec arrowLen)))
    (entmake (list '(0 . "CIRCLE") '(8 . "0") '(62 . 1) (cons 10 ptOnBeam) (cons 40 tipR)))
    (entmake (list '(0 . "LINE") '(8 . "0") '(62 . 1) (cons 10 ptTail) (cons 11 tip)))
    (setq i (1+ i))
  )
  (setq labelPt (vec-sub (vec-scale beamVec 0.5) (vec-scale unitVec (* arrowLen 1.25))))
  (setq unitStr (normalize-dist-unit unitStr))
  (setq labelStr (strcat "q=" (rtos loadMag 2 1) " " unitStr " ("
                         (rtos (car unitVec) 2 2) ","
                         (rtos (cadr unitVec) 2 2) ","
                         (rtos (caddr unitVec) 2 2) ")"))
  (entmake (list '(0 . "TEXT") '(8 . "0") '(62 . 1) (cons 10 labelPt) (cons 40 (* arrowLen 0.25)) (cons 1 labelStr)))
  (setq blkDefName (entmake '((0 . "ENDBLK"))))
  (setq blkRef (entmakex (list '(0 . "INSERT") '(8 . "CAE_VIS_LOAD") (cons 2 blkDefName) (cons 10 p1))))
  (lock-vis-layer)
  blkRef
)

(defun remove-old-visual (beamEnt / entData xdata appData visHandle oldBlkEnt)
  (setq entData (entget beamEnt '("MY_CAE_LOAD")))
  (setq xdata (assoc -3 entData))
  (if xdata
    (progn
      (setq appData (cdr (cadr xdata)))
      (if (> (length appData) 4)
        (progn
          (setq visHandle (cdr (nth 4 appData)))
          (if (and visHandle (setq oldBlkEnt (handent visHandle)))
            (if (entget oldBlkEnt)
              (progn (unlock-vis-layer) (entdel oldBlkEnt) (lock-vis-layer))
            )
          )
        )
      )
    )
  )
)

(defun c:SETLOAD (/ ss loadMag unitStr unitVec i beamEnt beamHandle visBlkEnt visHandle nSkip nOk)
  (register-all-cae-apps)
  (princ (_T "\n请选择要施加分布载荷的梁直线 (杆 ROD 不可用): "
             "\nSelect beam lines for distributed load (ROD not allowed): "))
  (setq ss (ssget '((0 . "LINE"))))
  (if ss
    (progn
      (setq loadMag (getreal (_T "\n均布载荷集度数值 <10.0>: "
                                 "\nDistributed load magnitude <10.0>: ")))
      (if (not loadMag) (setq loadMag 10.0))
      (setq unitStr (ask-dist-unit))
      (setq unitVec (ask-unit-vec))
      (if unitVec
        (progn
          (setq i 0 nSkip 0 nOk 0)
          (while (< i (sslength ss))
            (setq beamEnt (ssname ss i))
            (if (cae-is-rod beamEnt)
              (setq nSkip (1+ nSkip))
              (progn
                (setq beamHandle (cdr (assoc 5 (entget beamEnt))))
                (remove-old-visual beamEnt)
                (setq visBlkEnt (create-load-block beamEnt loadMag unitVec unitStr))
                (setq visHandle (cdr (assoc 5 (entget visBlkEnt))))
                (entmod (append (entget beamEnt)
                                (list (list -3 (list "MY_CAE_LOAD"
                                  (cons 1000 "Distributed") (cons 1040 loadMag)
                                  (cons 1000 unitStr) (cons 1013 unitVec)
                                  (cons 1005 visHandle))))))
                (entupd beamEnt)
                (entmod (append (entget visBlkEnt)
                                (list (list -3 (list "MY_CAE_LOAD" (cons 1005 beamHandle))))))
                (setq nOk (1+ nOk))
              )
            )
            (setq i (1+ i))
          )
          (princ (strcat (_T "\n[成功] 已为 " "\n[OK] Wrote distributed load on ")
                         (itoa nOk)
                         (_T " 根梁写入分布载荷 (" " beam(s) (")
                         unitStr
                         (_T ")。" ").")))
          (if (> nSkip 0)
            (princ (strcat (_T " 跳过 " " Skipped ") (itoa nSkip)
                           (_T " 根杆。" " rod(s).")))
          )
        )
        (princ (_T "\n[错误] 方向向量无效。" "\n[Error] Invalid direction vector."))
      )
    )
    (princ (_T "\n[取消] 未选中直线。" "\n[Cancel] No lines selected."))
  )
  (princ)
)

(defun c:DELLOAD (/ ss i ent entData entType xdata appData targetEnt)
  (unlock-vis-layer)
  (princ (_T "\n请选择【梁】或【载荷符号】(LINE/INSERT): " "\nSelect beam(s) or load symbol(s) (LINE/INSERT): "))
  (setq ss (ssget '((0 . "LINE,INSERT"))))
  (if ss
    (progn
      (setq i 0)
      (while (< i (sslength ss))
        (setq ent (ssname ss i))
        (setq entData (entget ent '("MY_CAE_LOAD")))
        (setq entType (cdr (assoc 0 entData)))
        (setq xdata (assoc -3 entData))
        (if xdata
          (progn
            (setq appData (cdr (cadr xdata)))
            (cond
              ((= entType "LINE")
               (if (> (length appData) 4)
                 (if (setq targetEnt (handent (cdr (nth 4 appData))))
                   (if (entget targetEnt) (entdel targetEnt))
                 )
               )
               (entmod (append (entget ent) (list (list -3 (list "MY_CAE_LOAD")))))
               (entupd ent)
              )
              ((= entType "INSERT")
               (if (setq targetEnt (handent (cdr (nth 0 appData))))
                 (if (entget targetEnt)
                   (progn
                     (entmod (append (entget targetEnt) (list (list -3 (list "MY_CAE_LOAD")))))
                     (entupd targetEnt)
                   )
                 )
               )
               (entdel ent)
              )
            )
          )
        )
        (setq i (1+ i))
      )
      (princ (_T "\n[清除完成] 分布载荷已双向删除。" "\n[Done] Distributed load removed."))
    )
  )
  (lock-vis-layer)
  (princ)
)

;;; ====================================================================
;;; 集中力  MY_CAE_POINT_LOAD
;;; ====================================================================
(defun create-ptload-block (ptNode beamLen forceMag unitVec endTag unitStr /
                            arrowLen r tip ptTail ptConeBase perp1 perp2 pWing1 pWing2
                            labelPt labelStr blkDefName blkRef)
  (unlock-vis-layer)
  (setq arrowLen (* beamLen 0.18))
  (if (< arrowLen 150.0) (setq arrowLen 150.0))
  (setq arrowLen (* arrowLen *CAE_SCALE_LOAD*))
  (setq r (* arrowLen 0.08))
  (entmake (list '(0 . "BLOCK") '(2 . "*U") '(70 . 1) '(10 0.0 0.0 0.0)))
  ;; 端点用小圆标记；箭头落在圆周上，不压住端点
  (entmake (list '(0 . "CIRCLE") '(8 . "0") '(62 . 3) '(10 0.0 0.0 0.0) (cons 40 r)))
  (setq tip (vec-scale unitVec (- r)))
  (setq ptTail (vec-sub tip (vec-scale unitVec arrowLen)))
  (entmake (list '(0 . "LINE") '(8 . "0") '(62 . 3) (cons 10 ptTail) (cons 11 tip)))
  (setq ptConeBase (vec-sub tip (vec-scale unitVec (* arrowLen 0.25))))
  (if (< (abs (car unitVec)) 0.9)
    (setq perp1 (vec-unit (list 0.0 (- (caddr unitVec)) (cadr unitVec))))
    (setq perp1 (vec-unit (list (- (caddr unitVec)) 0.0 (car unitVec))))
  )
  (setq perp2 (vec-unit (vec-cross unitVec perp1)))
  (foreach p (list perp1 perp2)
    (setq pWing1 (vec-add ptConeBase (vec-scale p (* arrowLen 0.09))))
    (setq pWing2 (vec-sub ptConeBase (vec-scale p (* arrowLen 0.09))))
    (entmake (list '(0 . "LINE") '(8 . "0") '(62 . 3) (cons 10 pWing1) (cons 11 tip)))
    (entmake (list '(0 . "LINE") '(8 . "0") '(62 . 3) (cons 10 pWing2) (cons 11 tip)))
  )
  (setq labelPt (vec-add ptTail (list 0.0 0.0 (- (* arrowLen 0.15)))))
  (if (or (not unitStr) (= unitStr "")) (setq unitStr "N"))
  (setq labelStr (strcat "F[" endTag "]=" (rtos forceMag 2 1) unitStr))
  (entmake (list '(0 . "TEXT") '(8 . "0") '(62 . 3) (cons 10 labelPt) (cons 40 (* arrowLen 0.2)) (cons 1 labelStr)))
  (setq blkDefName (entmake '((0 . "ENDBLK"))))
  (setq blkRef (entmakex (list '(0 . "INSERT") '(8 . "CAE_VIS_LOAD") (cons 2 blkDefName) (cons 10 ptNode))))
  (lock-vis-layer)
  blkRef
)

(defun remove-old-ptload-visual (beamEnt targetEndTag / entData xdata appData i handle oldBlk stride)
  (setq entData (entget beamEnt '("MY_CAE_POINT_LOAD")))
  (setq xdata (assoc -3 entData))
  (if xdata
    (progn
      (setq appData (cdr (cadr xdata)) i 0 stride (ptload-stride appData))
      (while (< i (length appData))
        (if (= (cdr (nth i appData)) targetEndTag)
          (progn
            (setq handle (cdr (nth (+ i 3) appData)))
            (if (and handle (setq oldBlk (handent handle)))
              (if (entget oldBlk)
                (progn (unlock-vis-layer) (entdel oldBlk) (lock-vis-layer))
              )
            )
          )
        )
        (setq i (+ i stride))
      )
    )
  )
)

(defun c:SETPTLOAD (/ ent entData beamHandle p1 p2 beamLen endInfo ptNode endTag forceMag unitStr unitVec visBlkEnt visHandle oldXdata oldAppData newRecords i otherPt)
  (register-all-cae-apps)
  (setq ent (car (entsel (_T "\n[第1步] 选择梁/杆直线 (LINE): " "\n[Step 1] Select a beam/rod LINE: "))))
  (if (and ent (= (cdr (assoc 0 (setq entData (entget ent)))) "LINE"))
    (progn
      (setq beamHandle (cdr (assoc 5 entData)))
      (setq p1 (cdr (assoc 10 entData)) p2 (cdr (assoc 11 entData)))
      (setq beamLen (distance p1 p2))
      (setq endInfo (pick-beam-end ent))
      (if endInfo
        (progn
          (setq ptNode (car endInfo) endTag (cadr endInfo))
          (if (cae-is-rod ent)
            (progn
              ;; 杆：仅轴向端点力；+拉 -压；方向指向另一端
              (setq forceMag (getreal (strcat (_T "\n" "\n") endTag
                (_T " 轴向力(+拉/-压) <50.0>: " " axial F(+ten/-comp) <50.0>: "))))
              (if (not forceMag) (setq forceMag 50.0))
              (setq unitStr (ask-force-unit))
              (setq otherPt (if (= endTag "START") p2 p1))
              (setq unitVec (vec-unit (vec-sub otherPt ptNode)))
              (if unitVec
                (progn
                  (remove-old-ptload-visual ent endTag)
                  (setq visBlkEnt (create-ptload-block ptNode beamLen (abs forceMag) unitVec endTag unitStr))
                  (setq visHandle (cdr (assoc 5 (entget visBlkEnt))))
                  (setq oldXdata (assoc -3 (entget ent '("MY_CAE_POINT_LOAD"))))
                  (setq newRecords nil)
                  (if oldXdata
                    (setq newRecords (xdata-drop-end (cdr (cadr oldXdata)) endTag
                                       (ptload-stride (cdr (cadr oldXdata)))))
                  )
                  (setq newRecords (append newRecords (list
                    (cons 1000 endTag) (cons 1040 forceMag)
                    (cons 1013 unitVec) (cons 1005 visHandle)
                    (cons 1000 unitStr))))
                  (entmod (append (entget ent) (list (list -3 (cons "MY_CAE_POINT_LOAD" newRecords)))))
                  (entupd ent)
                  (entmod (append (entget visBlkEnt)
                                  (list (list -3 (list "MY_CAE_POINT_LOAD"
                                    (cons 1005 beamHandle) (cons 1000 endTag))))))
                  (princ (strcat (_T "\n[成功] 杆[" "\n[OK] Rod[") endTag "] F="
                                 (rtos forceMag 2 2) " " unitStr
                                 (_T " (+拉/-压)" " (+ten/-comp)")))
                )
                (princ (_T "\n[错误] 杆轴向方向无效。" "\n[Error] Invalid rod axis."))
              )
            )
            (progn
              (setq forceMag (getreal (strcat (_T "\n" "\n") endTag (_T " 集中力 <50.0>: " " force <50.0>: "))))
              (if (not forceMag) (setq forceMag 50.0))
              (setq unitStr (ask-force-unit))
              (setq unitVec (ask-unit-vec))
              (if unitVec
                (progn
                  (remove-old-ptload-visual ent endTag)
                  (setq visBlkEnt (create-ptload-block ptNode beamLen forceMag unitVec endTag unitStr))
                  (setq visHandle (cdr (assoc 5 (entget visBlkEnt))))
                  (setq oldXdata (assoc -3 (entget ent '("MY_CAE_POINT_LOAD"))))
                  (setq newRecords nil)
                  (if oldXdata
                    (setq newRecords (xdata-drop-end (cdr (cadr oldXdata)) endTag
                                       (ptload-stride (cdr (cadr oldXdata)))))
                  )
                  (setq newRecords (append newRecords (list
                    (cons 1000 endTag) (cons 1040 forceMag)
                    (cons 1013 unitVec) (cons 1005 visHandle)
                    (cons 1000 unitStr))))
                  (entmod (append (entget ent) (list (list -3 (cons "MY_CAE_POINT_LOAD" newRecords)))))
                  (entupd ent)
                  (entmod (append (entget visBlkEnt)
                                  (list (list -3 (list "MY_CAE_POINT_LOAD"
                                    (cons 1005 beamHandle) (cons 1000 endTag))))))
                  (princ (strcat (_T "\n[成功] [" "\n[OK] [") endTag "] F=" (rtos forceMag 2 2) " " unitStr))
                )
                (princ (_T "\n[错误] 方向向量无效。" "\n[Error] Invalid direction vector."))
              )
            )
          )
        )
        (princ (_T "\n[取消] 未捕捉端点。" "\n[Cancel] No endpoint picked."))
      )
    )
    (princ (_T "\n[错误] 请选择 LINE。" "\n[Error] Select a LINE."))
  )
  (princ)
)

(defun c:DELPTLOAD (/ ss i ent entData entType xdata appData j handle oldBlk targetEnt targetEndTag oldXdata newRecords)
  (unlock-vis-layer)
  (princ (_T "\n请选择【梁】或【集中力箭头】: " "\nSelect beam(s) or point-load arrow(s): "))
  (setq ss (ssget '((0 . "LINE,INSERT"))))
  (if ss
    (progn
      (setq i 0)
      (while (< i (sslength ss))
        (setq ent (ssname ss i))
        (setq entData (entget ent '("MY_CAE_POINT_LOAD")))
        (setq entType (cdr (assoc 0 entData)))
        (setq xdata (assoc -3 entData))
        (if xdata
          (progn
            (setq appData (cdr (cadr xdata)))
            (cond
              ((= entType "LINE")
               (setq j 0)
               (while (< j (length appData))
                 (setq handle (cdr (nth (+ j 3) appData)))
                 (if (and handle (setq oldBlk (handent handle)))
                   (if (entget oldBlk) (entdel oldBlk))
                 )
                 (setq j (+ j (ptload-stride appData)))
               )
               (entmod (append (entget ent) (list (list -3 (list "MY_CAE_POINT_LOAD")))))
               (entupd ent)
              )
              ((= entType "INSERT")
               (setq targetEnt (handent (cdr (nth 0 appData))))
               (setq targetEndTag (cdr (nth 1 appData)))
               (if (and targetEnt (entget targetEnt))
                 (progn
                   (setq oldXdata (assoc -3 (entget targetEnt '("MY_CAE_POINT_LOAD"))))
                   (setq newRecords nil)
                   (if oldXdata
                     (setq newRecords (xdata-drop-end (cdr (cadr oldXdata)) targetEndTag
                                        (ptload-stride (cdr (cadr oldXdata)))))
                   )
                   (if newRecords
                     (entmod (append (entget targetEnt) (list (list -3 (cons "MY_CAE_POINT_LOAD" newRecords)))))
                     (entmod (append (entget targetEnt) (list (list -3 (list "MY_CAE_POINT_LOAD")))))
                   )
                   (entupd targetEnt)
                 )
               )
               (entdel ent)
              )
            )
          )
        )
        (setq i (1+ i))
      )
      (princ (_T "\n[清除完成] 集中力已双向删除。" "\n[Done] Point load removed."))
    )
  )
  (lock-vis-layer)
  (princ)
)

;;; ====================================================================
;;; 集中弯矩  MY_CAE_MOMENT
;;; XData 每端 5 项: endTag | Mag | axis(1013) | visHandle | unit
;;; 可视化: 端点小圆 + 绕轴圆弧(半径>圆，不压端点) + 弧端小箭头
;;; ====================================================================
(defun create-moment-block (ptNode beamLen momMag axisVec endTag unitStr sense /
                            sz r R basis e1 e2 e3 nSeg i a0 a1 ang0 ang1
                            pA pB pTip tang wing nWing pW1 pW2
                            labelPt labelStr blkDefName blkRef)
  (unlock-vis-layer)
  (setq sz (* beamLen 0.18))
  (if (< sz 150.0) (setq sz 150.0))
  (setq sz (* sz *CAE_SCALE_LOAD*))
  (setq r (* sz 0.08) R (* sz 0.38))
  (setq e1 (vec-unit axisVec))
  (if (not e1) (setq e1 '(0.0 0.0 1.0)))
  (setq basis (make-local-basis e1) e2 (cadr basis) e3 (caddr basis))
  ;; sense: "CW" 取反 e3 → 弧反向
  (if (= sense "CW") (setq e3 (vec-scale e3 -1.0)))
  (setq ang0 (* pi 0.20) ang1 (+ ang0 (* pi (/ 200.0 180.0))) nSeg 18)
  (entmake (list '(0 . "BLOCK") '(2 . "*U") '(70 . 1) '(10 0.0 0.0 0.0)))
  ;; 端点圆（与集中力一致，不压选点）
  (entmake (list '(0 . "CIRCLE") '(8 . "0") '(62 . 1) '(10 0.0 0.0 0.0) (cons 40 r)
                 (cons 210 e1)))
  (setq i 0 pB nil)
  (while (< i nSeg)
    (setq a0 (+ ang0 (* (/ (float i) (float nSeg)) (- ang1 ang0))))
    (setq a1 (+ ang0 (* (/ (float (1+ i)) (float nSeg)) (- ang1 ang0))))
    (setq pA (vec-add (vec-scale e2 (* R (cos a0))) (vec-scale e3 (* R (sin a0)))))
    (setq pB (vec-add (vec-scale e2 (* R (cos a1))) (vec-scale e3 (* R (sin a1)))))
    (entmake (list '(0 . "LINE") '(8 . "0") '(62 . 1) (cons 10 pA) (cons 11 pB)))
    (setq i (1+ i))
  )
  ;; 弧末端小箭头（细翼，贴切线）
  (setq tang (vec-unit (vec-add (vec-scale e2 (* -1.0 R (sin ang1)))
                                (vec-scale e3 (* R (cos ang1))))))
  (setq pTip pB)
  (setq wing (vec-scale tang (* R -0.22)))
  (setq nWing (vec-scale e1 (* R 0.10)))
  (setq pW1 (vec-add (vec-add pTip wing) nWing))
  (setq pW2 (vec-sub (vec-add pTip wing) nWing))
  (entmake (list '(0 . "LINE") '(8 . "0") '(62 . 1) (cons 10 pW1) (cons 11 pTip)))
  (entmake (list '(0 . "LINE") '(8 . "0") '(62 . 1) (cons 10 pW2) (cons 11 pTip)))
  (setq labelPt (vec-add (vec-scale e2 (* R 0.15)) (vec-scale e3 (* R 1.15))))
  (if (or (not unitStr) (= unitStr "")) (setq unitStr "Nmm"))
  (setq labelStr (strcat "M[" endTag "]=" (rtos momMag 2 1) " " unitStr))
  (entmake (list '(0 . "TEXT") '(8 . "0") '(62 . 1) (cons 10 labelPt)
                 (cons 40 (* sz 0.18)) (cons 1 labelStr)))
  (setq blkDefName (entmake '((0 . "ENDBLK"))))
  (setq blkRef (entmakex (list '(0 . "INSERT") '(8 . "CAE_VIS_LOAD")
                               (cons 2 blkDefName) (cons 10 ptNode))))
  (lock-vis-layer)
  blkRef
)

(defun remove-old-moment-visual (beamEnt targetEndTag / entData xdata appData i handle oldBlk)
  (setq entData (entget beamEnt '("MY_CAE_MOMENT")))
  (setq xdata (assoc -3 entData))
  (if xdata
    (progn
      (setq appData (cdr (cadr xdata)) i 0)
      (while (< i (length appData))
        (if (= (cdr (nth i appData)) targetEndTag)
          (progn
            (setq handle (cdr (nth (+ i 3) appData)))
            (if (and handle (setq oldBlk (handent handle)))
              (if (entget oldBlk)
                (progn (unlock-vis-layer) (entdel oldBlk) (lock-vis-layer))
              )
            )
          )
        )
        (setq i (+ i 5))
      )
    )
  )
)

(defun c:SETMOMENT (/ ent entData beamHandle p1 p2 beamLen endInfo ptNode endTag
                      momMag unitStr axisMode axisVec axA axB sense visBlkEnt visHandle
                      oldXdata newRecords)
  (register-all-cae-apps)
  (setq ent (car (entsel (_T "\n[第1步] 选择梁直线 (LINE): " "\n[Step 1] Select a beam line (LINE): "))))
  (if (and ent (= (cdr (assoc 0 (setq entData (entget ent)))) "LINE"))
    (if (cae-is-rod ent)
      (princ (_T "\n[错误] 杆(ROD)不能施加弯矩，仅允许端点轴向集中力。"
                 "\n[Error] ROD cannot take moments; axial end force only."))
    (progn
      (setq beamHandle (cdr (assoc 5 entData)))
      (setq p1 (cdr (assoc 10 entData)) p2 (cdr (assoc 11 entData)))
      (setq beamLen (distance p1 p2))
      (setq endInfo (pick-beam-end ent))
      (if endInfo
        (progn
          (setq ptNode (car endInfo) endTag (cadr endInfo))
          (setq momMag (getreal (strcat (_T "\n" "\n") endTag (_T " 弯矩 <1000.0>: " " moment <1000.0>: "))))
          (if (not momMag) (setq momMag 1000.0))
          (setq unitStr (ask-moment-unit))
          (initget "BeamAxis Vector Pick")
          (setq axisMode (getkword (_T "\n弯矩轴 [BeamAxis/Vector/Pick] <BeamAxis>: "
                                       "\nMoment axis [BeamAxis/Vector/Pick] <BeamAxis>: ")))
          (if (not axisMode) (setq axisMode "BeamAxis"))
          (setq axisVec
            (cond
              ((= axisMode "BeamAxis") (vec-unit (vec-sub p2 p1)))
              ((= axisMode "Vector")
               (progn
                 (setq axA (getpoint (_T "\n轴向量 X,Y,Z <0,0,1>: "
                                         "\nAxis vector X,Y,Z <0,0,1>: ")))
                 (if (not axA) (setq axA '(0.0 0.0 1.0)))
                 (vec-unit axA)
               )
              )
              (T
               (progn
                 (setq axA (getpoint (_T "\n轴起点: " "\nAxis start: ")))
                 (if axA (setq axB (getpoint axA (_T "\n轴终点: " "\nAxis end: "))))
                 (if (and axA axB)
                   (vec-unit (mapcar '- (trans axB 1 0) (trans axA 1 0)))
                   nil
                 )
               )
              )
            )
          )
          (initget "CCW CW")
          (setq sense (getkword (_T "\n转向 [CCW/CW] <CCW>: "
                                    "\nSense [CCW/CW] <CCW>: ")))
          (if (not sense) (setq sense "CCW"))
          (if axisVec
            (progn
              (remove-old-moment-visual ent endTag)
              (setq visBlkEnt (create-moment-block ptNode beamLen momMag axisVec endTag unitStr sense))
              (setq visHandle (cdr (assoc 5 (entget visBlkEnt))))
              ;; 存右手系：CW 时轴取反，刷新一律按轴画（sense=CCW）
              (if (= sense "CW") (setq axisVec (vec-scale axisVec -1.0)))
              (setq oldXdata (assoc -3 (entget ent '("MY_CAE_MOMENT"))))
              (setq newRecords nil)
              (if oldXdata
                (setq newRecords (xdata-drop-end (cdr (cadr oldXdata)) endTag 5))
              )
              (setq newRecords (append newRecords (list
                (cons 1000 endTag) (cons 1040 momMag)
                (cons 1013 axisVec) (cons 1005 visHandle)
                (cons 1000 unitStr))))
              (entmod (append (entget ent) (list (list -3 (cons "MY_CAE_MOMENT" newRecords)))))
              (entupd ent)
              (entmod (append (entget visBlkEnt)
                              (list (list -3 (list "MY_CAE_MOMENT"
                                (cons 1005 beamHandle) (cons 1000 endTag))))))
              (princ (strcat (_T "\n[成功] [" "\n[OK] [") endTag "] M="
                             (rtos momMag 2 2) " " unitStr))
            )
            (princ (_T "\n[错误] 弯矩轴无效。" "\n[Error] Invalid moment axis."))
          )
        )
        (princ (_T "\n[取消] 未捕捉端点。" "\n[Cancel] No endpoint picked."))
      )
    )
    ) ; end (if cae-is-rod …)
    (princ (_T "\n[错误] 请选择 LINE。" "\n[Error] Select a LINE."))
  )
  (princ)
)

(defun c:DELMOMENT (/ ss i ent entData entType xdata appData j handle oldBlk
                      targetEnt targetEndTag oldXdata newRecords)
  (unlock-vis-layer)
  (princ (_T "\n请选择【梁】或【弯矩符号】: " "\nSelect beam(s) or moment symbol(s): "))
  (setq ss (ssget '((0 . "LINE,INSERT"))))
  (if ss
    (progn
      (setq i 0)
      (while (< i (sslength ss))
        (setq ent (ssname ss i))
        (setq entData (entget ent '("MY_CAE_MOMENT")))
        (setq entType (cdr (assoc 0 entData)))
        (setq xdata (assoc -3 entData))
        (if xdata
          (progn
            (setq appData (cdr (cadr xdata)))
            (cond
              ((= entType "LINE")
               (setq j 0)
               (while (< j (length appData))
                 (setq handle (cdr (nth (+ j 3) appData)))
                 (if (and handle (setq oldBlk (handent handle)))
                   (if (entget oldBlk) (entdel oldBlk))
                 )
                 (setq j (+ j 5))
               )
               (entmod (append (entget ent) (list (list -3 (list "MY_CAE_MOMENT")))))
               (entupd ent)
              )
              ((= entType "INSERT")
               (setq targetEnt (handent (cdr (nth 0 appData))))
               (setq targetEndTag (cdr (nth 1 appData)))
               (if (and targetEnt (entget targetEnt))
                 (progn
                   (setq oldXdata (assoc -3 (entget targetEnt '("MY_CAE_MOMENT"))))
                   (setq newRecords nil)
                   (if oldXdata
                     (setq newRecords (xdata-drop-end (cdr (cadr oldXdata)) targetEndTag 5))
                   )
                   (if newRecords
                     (entmod (append (entget targetEnt) (list (list -3 (cons "MY_CAE_MOMENT" newRecords)))))
                     (entmod (append (entget targetEnt) (list (list -3 (list "MY_CAE_MOMENT")))))
                   )
                   (entupd targetEnt)
                 )
               )
               (entdel ent)
              )
            )
          )
        )
        (setq i (1+ i))
      )
      (princ (_T "\n[清除完成] 弯矩已双向删除。" "\n[Done] Moment load removed."))
    )
  )
  (lock-vis-layer)
  (princ)
)

;;; ====================================================================
;;; 简单端点约束  MY_CAE_BC
;;; 对齐 K：端点小圆(XY) + 沿 -Z；两圆同面，连线在圆周 (r,0,z)
;;; ====================================================================
(defun create-bc-block (ptNode beamLen bcMode maskStr e1 e2 e3 endTag /
                        sz r gap stem c2 pL1 pL2 axEnd labelPt labelStr blkDefName blkRef)
  (unlock-vis-layer)
  (setq sz (* beamLen 0.12))
  (if (< sz 100.0) (setq sz 100.0))
  (setq sz (* sz *CAE_SCALE_BC*))
  (setq r (* sz 0.10) gap (* sz 0.08) stem (* sz 0.70))
  ;; 远端圆心：两圆之间留 gap+stem，连线只接相对外缘，不穿心
  (setq c2 (list 0.0 0.0 (- (+ r gap stem r))))
  (setq pL1 (list 0.0 0.0 (- r))
        pL2 (list 0.0 0.0 (+ (caddr c2) r)))
  (entmake (list '(0 . "BLOCK") '(2 . "*U") '(70 . 1) '(10 0.0 0.0 0.0)))
  (entmake (list '(0 . "CIRCLE") '(8 . "0") '(62 . 4) '(10 0.0 0.0 0.0) (cons 40 r) '(210 0.0 0.0 1.0)))
  (entmake (list '(0 . "CIRCLE") '(8 . "0") '(62 . 4) (cons 10 c2) (cons 40 r) '(210 0.0 0.0 1.0)))
  (entmake (list '(0 . "LINE") '(8 . "0") '(62 . 4) (cons 10 pL1) (cons 11 pL2)))
  (if (and (/= bcMode "GLOBAL") e1)
    (progn
      (setq axEnd (vec-add c2 (vec-scale e1 (* sz 0.55))))
      (entmake (list '(0 . "LINE") '(8 . "0") '(62 . 2) (cons 10 c2) (cons 11 axEnd)))
    )
  )
  (setq labelPt (list (* sz 0.05) (* sz 0.05) (- (+ r gap stem r (* sz 0.15)))))
  (setq labelStr (strcat "BC[" endTag "]:" bcMode "[" maskStr "]"))
  (entmake (list '(0 . "TEXT") '(8 . "0") '(62 . 4) (cons 10 labelPt) (cons 40 (* sz 0.20)) (cons 1 labelStr)))
  (setq blkDefName (entmake '((0 . "ENDBLK"))))
  (setq blkRef (entmakex (list '(0 . "INSERT") '(8 . "CAE_VIS_BC") (cons 2 blkDefName) (cons 10 ptNode))))
  (lock-vis-layer)
  blkRef
)

(defun remove-old-bc-visual (beamEnt targetEndTag / entData xdata appData i handle oldBlk)
  (setq entData (entget beamEnt '("MY_CAE_BC")))
  (setq xdata (assoc -3 entData))
  (if xdata
    (progn
      (setq appData (cdr (cadr xdata)) i 0)
      (while (< i (length appData))
        (if (= (cdr (nth i appData)) targetEndTag)
          (progn
            (setq handle (cdr (nth (+ i 5) appData)))
            (if (and handle (setq oldBlk (handent handle)))
              (if (entget oldBlk)
                (progn (unlock-vis-layer) (entdel oldBlk) (lock-vis-layer))
              )
            )
          )
        )
        (setq i (+ i 6))
      )
    )
  )
)

(defun c:SETBC (/ ent entData beamHandle p1 p2 beamLen endInfo ptNode endTag bcChoice bcMode maskStr pA pB v1 v2 e1 e2 e3 basis rotOpt visBlkEnt visHandle oldXdata newRecords)
  (register-all-cae-apps)
  (setq ent (car (entsel (_T "\n[第1步] 选择梁直线 (LINE): " "\n[Step 1] Select a beam line (LINE): "))))
  (if (and ent (= (cdr (assoc 0 (setq entData (entget ent)))) "LINE"))
    (progn
      (setq beamHandle (cdr (assoc 5 entData)))
      (setq p1 (cdr (assoc 10 entData)) p2 (cdr (assoc 11 entData)))
      (setq beamLen (distance p1 p2))
      (setq endInfo (pick-beam-end ent))
      (if endInfo
        (progn
          (setq ptNode (car endInfo) endTag (cadr endInfo))
          (initget "Mask Plane Slide RotAxis")
          (setq bcChoice (getkword (strcat (_T "\n" "\n") endTag (_T " 约束类型 [Mask/Plane/Slide/RotAxis] <Mask>: " " BC type [Mask/Plane/Slide/RotAxis] <Mask>: "))))
          (if (not bcChoice) (setq bcChoice "Mask"))
          (setq e1 nil)
          (cond
            ((= bcChoice "Mask")
             (setq bcMode "GLOBAL")
             (setq maskStr (getstring (_T "\n6位掩码 UXUYUZ RXRYRZ <111111>: " "\n6-bit mask UXUYUZ RXRYRZ <111111>: ")))
             (if (= maskStr "") (setq maskStr "111111"))
             (setq e1 '(1.0 0.0 0.0) e2 '(0.0 1.0 0.0) e3 '(0.0 0.0 1.0))
            )
            ((= bcChoice "Plane")
             (setq bcMode "PLANE" maskStr "100000")
             (setq pA (getpoint (_T "\n平面内第2点: " "\n2nd point in plane: ")))
             (if pA (setq pB (getpoint (_T "\n平面内第3点: " "\n3rd point in plane: "))))
             (if (and pA pB)
               (progn
                 (setq v1 (vec-sub (trans pA 1 0) ptNode))
                 (setq v2 (vec-sub (trans pB 1 0) ptNode))
                 (setq e1 (vec-unit (vec-cross v1 v2)))
                 (if e1
                   (progn (setq basis (make-local-basis e1)) (setq e2 (cadr basis) e3 (caddr basis)))
                   (princ (_T "\n[错误] 三点共线。" "\n[Error] Three points are colinear."))
                 )
               )
             )
            )
            ((= bcChoice "Slide")
             (setq bcMode "SLIDE" maskStr "011000")
             (setq pA (getpoint (_T "\n滑移方向线上第2点: " "\n2nd point on slide direction: ")))
             (if pA
               (progn
                 (setq e1 (vec-unit (vec-sub (trans pA 1 0) ptNode)))
                 (if e1
                   (progn (setq basis (make-local-basis e1)) (setq e2 (cadr basis) e3 (caddr basis)))
                   (princ (_T "\n[错误] 滑移方向无效。" "\n[Error] Invalid slide direction."))
                 )
               )
             )
            )
            ((= bcChoice "RotAxis")
             (setq bcMode "ROTAXIS" maskStr "000100")
             (initget "BeamAxis PickLine")
             (setq rotOpt (getkword (_T "\n旋转轴 [BeamAxis/PickLine] <BeamAxis>: " "\nRotation axis [BeamAxis/PickLine] <BeamAxis>: ")))
             (if (not rotOpt) (setq rotOpt "BeamAxis"))
             (if (= rotOpt "BeamAxis")
               (setq e1 (vec-unit (vec-sub p2 p1)))
               (progn
                 (setq pA (getpoint (_T "\n旋转轴上第2点: " "\n2nd point on rotation axis: ")))
                 (if pA (setq e1 (vec-unit (vec-sub (trans pA 1 0) ptNode))))
               )
             )
             (if e1
               (progn (setq basis (make-local-basis e1)) (setq e2 (cadr basis) e3 (caddr basis)))
               (princ (_T "\n[错误] 旋转轴无效。" "\n[Error] Invalid rotation axis."))
             )
            )
          )
          (if e1
            (progn
              (remove-old-bc-visual ent endTag)
              (setq visBlkEnt (create-bc-block ptNode beamLen bcMode maskStr e1 e2 e3 endTag))
              (setq visHandle (cdr (assoc 5 (entget visBlkEnt))))
              (setq oldXdata (assoc -3 (entget ent '("MY_CAE_BC"))))
              (setq newRecords nil)
              (if oldXdata
                (setq newRecords (xdata-drop-end (cdr (cadr oldXdata)) endTag 6))
              )
              (setq newRecords (append newRecords (list
                (cons 1000 endTag) (cons 1000 bcMode) (cons 1000 maskStr)
                (cons 1013 e1) (cons 1013 e2) (cons 1005 visHandle))))
              (entmod (append (entget ent) (list (list -3 (cons "MY_CAE_BC" newRecords)))))
              (entupd ent)
              (entmod (append (entget visBlkEnt)
                              (list (list -3 (list "MY_CAE_BC"
                                (cons 1005 beamHandle) (cons 1000 endTag))))))
              (princ (strcat (_T "\n[成功] [" "\n[OK] [") endTag "] " bcMode " [" maskStr "]"))
            )
          )
        )
      )
    )
    (princ (_T "\n[错误] 请选择 LINE。" "\n[Error] Select a LINE."))
  )
  (princ)
)

(defun c:DELBC (/ ss i ent entData entType xdata appData j handle oldBlk targetEnt targetEndTag oldXdata newRecords)
  (unlock-vis-layer)
  (princ (_T "\n请选择【梁】或【支座符号】: " "\nSelect beam(s) or support symbol(s): "))
  (setq ss (ssget '((0 . "LINE,INSERT"))))
  (if ss
    (progn
      (setq i 0)
      (while (< i (sslength ss))
        (setq ent (ssname ss i))
        (setq entData (entget ent '("MY_CAE_BC")))
        (setq entType (cdr (assoc 0 entData)))
        (setq xdata (assoc -3 entData))
        (if xdata
          (progn
            (setq appData (cdr (cadr xdata)))
            (cond
              ((= entType "LINE")
               (setq j 0)
               (while (< j (length appData))
                 (setq handle (cdr (nth (+ j 5) appData)))
                 (if (and handle (setq oldBlk (handent handle)))
                   (if (entget oldBlk) (entdel oldBlk))
                 )
                 (setq j (+ j 6))
               )
               (entmod (append (entget ent) (list (list -3 (list "MY_CAE_BC")))))
               (entupd ent)
              )
              ((= entType "INSERT")
               (setq targetEnt (handent (cdr (nth 0 appData))))
               (setq targetEndTag (cdr (nth 1 appData)))
               (if (and targetEnt (entget targetEnt))
                 (progn
                   (setq oldXdata (assoc -3 (entget targetEnt '("MY_CAE_BC"))))
                   (setq newRecords nil)
                   (if oldXdata
                     (setq newRecords (xdata-drop-end (cdr (cadr oldXdata)) targetEndTag 6))
                   )
                   (if newRecords
                     (entmod (append (entget targetEnt) (list (list -3 (cons "MY_CAE_BC" newRecords)))))
                     (entmod (append (entget targetEnt) (list (list -3 (list "MY_CAE_BC")))))
                   )
                   (entupd targetEnt)
                 )
               )
               (entdel ent)
              )
            )
          )
        )
        (setq i (1+ i))
      )
      (princ (_T "\n[清除完成] 简单约束已双向删除。" "\n[Done] Simple BC removed."))
    )
  )
  (lock-vis-layer)
  (princ)
)

;;; ====================================================================
;;; 梁端弹性支撑  MY_CAE_SPRING（线刚度 TRANS / 转动刚度 ROT，可独立施加）
;;; 记录步长 7：endTag, kind, k1, k2, k3, unit, visHandle
;;; ====================================================================
(defun xdata-drop-end-kind (appData targetEndTag kindTag stride / i j newRecords)
  (setq newRecords nil i 0)
  (while (< i (length appData))
    (if (not (and (= (cdr (nth i appData)) targetEndTag)
                  (= (cdr (nth (+ i 1) appData)) kindTag)))
      (progn
        (setq j 0)
        (while (< j stride)
          (setq newRecords (append newRecords (list (nth (+ i j) appData))))
          (setq j (1+ j))
        )
      )
    )
    (setq i (+ i stride))
  )
  newRecords
)

(defun remove-old-spring-visual (beamEnt targetEndTag kindTag / entData xdata appData i handle oldBlk)
  (setq entData (entget beamEnt '("MY_CAE_SPRING")))
  (setq xdata (assoc -3 entData))
  (if xdata
    (progn
      (setq appData (cdr (cadr xdata)) i 0)
      (while (< i (length appData))
        (if (and (= (cdr (nth i appData)) targetEndTag)
                 (= (cdr (nth (+ i 1) appData)) kindTag))
          (progn
            (setq handle (cdr (nth (+ i 6) appData)))
            (if (and handle (setq oldBlk (handent handle)))
              (if (entget oldBlk)
                (progn (unlock-vis-layer) (entdel oldBlk) (lock-vis-layer))
              )
            )
          )
        )
        (setq i (+ i 7))
      )
    )
  )
)

;;; 线刚度 K：端点小圆，沿 -Z 折线弹簧
(defun create-trans-spring-block (ptNode beamLen kx ky kz unitStr endTag /
                                  sz r gap amp i z0 z1 pA pB zig labelPt labelStr blkDefName blkRef)
  (unlock-vis-layer)
  (setq sz (* beamLen 0.12))
  (if (< sz 100.0) (setq sz 100.0))
  (setq sz (* sz *CAE_SCALE_BC*))
  (setq r (* sz 0.10) gap (* sz 0.08) amp (* sz 0.18))
  (entmake (list '(0 . "BLOCK") '(2 . "*U") '(70 . 1) '(10 0.0 0.0 0.0)))
  (entmake (list '(0 . "CIRCLE") '(8 . "0") '(62 . 3) '(10 0.0 0.0 0.0) (cons 40 r) '(210 0.0 0.0 1.0)))
  (entmake (list '(0 . "LINE") '(8 . "0") '(62 . 3)
                 (cons 10 (list 0.0 0.0 (- r)))
                 (cons 11 (list 0.0 0.0 (- (+ r gap))))))
  (setq i 0)
  (while (< i 6)
    (setq z0 (- (+ r gap (* (/ (float i) 6.0) (* sz 0.70)))))
    (setq z1 (- (+ r gap (* (/ (float (1+ i)) 6.0) (* sz 0.70)))))
    (setq pA (list (if (= (rem i 2) 0) amp (- amp)) 0.0 z0))
    (setq pB (list (if (= (rem i 2) 0) (- amp) amp) 0.0 z1))
    (if (= i 0) (setq pA (list 0.0 0.0 (- (+ r gap)))))
    (if (= i 5) (setq pB (list 0.0 0.0 (- (+ r gap (* sz 0.70))))))
    (entmake (list '(0 . "LINE") '(8 . "0") '(62 . 3) (cons 10 pA) (cons 11 pB)))
    (setq i (1+ i))
  )
  (setq zig (list 0.0 0.0 (- (+ r gap (* sz 0.70)))))
  (entmake (list '(0 . "LINE") '(8 . "0") '(62 . 3)
                 (cons 10 (list (* sz 0.16) 0.0 (caddr zig)))
                 (cons 11 (list (- (* sz 0.16)) 0.0 (caddr zig)))))
  (setq labelPt (list (* sz 0.05) (* sz 0.05) (- (+ r gap (* sz 0.85)))))
  (if (or (not unitStr) (= unitStr "") (= unitStr "N/mm") (= unitStr "Nmm"))
    (setq unitStr "N-mm")
  )
  (if (= unitStr "kN/m") (setq unitStr "kN-m"))
  (setq labelStr (strcat "K[" endTag "]="
                         (rtos kx 2 2) "," (rtos ky 2 2) "," (rtos kz 2 2)
                         " " unitStr))
  (entmake (list '(0 . "TEXT") '(8 . "0") '(62 . 3) (cons 10 labelPt)
                 (cons 40 (* sz 0.20)) (cons 1 labelStr)))
  (setq blkDefName (entmake '((0 . "ENDBLK"))))
  (setq blkRef (entmakex (list '(0 . "INSERT") '(8 . "CAE_VIS_BC") (cons 2 blkDefName) (cons 10 ptNode))))
  (lock-vis-layer)
  blkRef
)

;;; 角刚度 KR：端点小圆，沿 -Z 螺线
(defun create-rot-spring-block (ptNode beamLen krx kry krz unitStr endTag /
                                sz r gap lead i ang rr p0 p1 labelPt labelStr blkDefName blkRef)
  (unlock-vis-layer)
  (setq sz (* beamLen 0.12))
  (if (< sz 100.0) (setq sz 100.0))
  (setq sz (* sz *CAE_SCALE_BC*))
  (setq r (* sz 0.10) gap (* sz 0.08))
  (entmake (list '(0 . "BLOCK") '(2 . "*U") '(70 . 1) '(10 0.0 0.0 0.0)))
  (entmake (list '(0 . "CIRCLE") '(8 . "0") '(62 . 6) '(10 0.0 0.0 0.0) (cons 40 r) '(210 0.0 0.0 1.0)))
  (setq lead (list 0.0 0.0 (- (+ r gap (* sz 0.35)))))
  (entmake (list '(0 . "LINE") '(8 . "0") '(62 . 6)
                 (cons 10 (list 0.0 0.0 (- r))) (cons 11 lead)))
  (setq i 0 p0 nil)
  (while (<= i 20)
    (setq ang (* (/ (float i) 20.0) (* 2.2 pi)))
    (setq rr (* sz (+ 0.10 (* (/ (float i) 20.0) 0.22))))
    (setq p1 (list (* rr (cos ang))
                   (* rr (sin ang))
                   (- (+ r gap (* sz 0.35) (* (/ (float i) 20.0) (* sz 0.35))))))
    (if p0
      (entmake (list '(0 . "LINE") '(8 . "0") '(62 . 6) (cons 10 p0) (cons 11 p1)))
    )
    (setq p0 p1 i (1+ i))
  )
  (setq labelPt (list (* sz 0.05) (* sz 0.05) (- (+ r gap (* sz 0.85)))))
  (if (or (not unitStr) (= unitStr "")) (setq unitStr "Nmm/rad"))
  (setq labelStr (strcat "KR[" endTag "]="
                         (rtos krx 2 2) "," (rtos kry 2 2) "," (rtos krz 2 2)
                         " " unitStr))
  (entmake (list '(0 . "TEXT") '(8 . "0") '(62 . 6) (cons 10 labelPt)
                 (cons 40 (* sz 0.20)) (cons 1 labelStr)))
  (setq blkDefName (entmake '((0 . "ENDBLK"))))
  (setq blkRef (entmakex (list '(0 . "INSERT") '(8 . "CAE_VIS_BC") (cons 2 blkDefName) (cons 10 ptNode))))
  (lock-vis-layer)
  blkRef
)

(defun write-spring-record (ent beamHandle endTag kindTag k1 k2 k3 unitStr visBlkEnt /
                            visHandle oldXdata newRecords)
  (setq visHandle (cdr (assoc 5 (entget visBlkEnt))))
  (setq oldXdata (assoc -3 (entget ent '("MY_CAE_SPRING"))))
  (setq newRecords nil)
  (if oldXdata
    (setq newRecords (xdata-drop-end-kind (cdr (cadr oldXdata)) endTag kindTag 7))
  )
  (setq newRecords (append newRecords (list
    (cons 1000 endTag) (cons 1000 kindTag)
    (cons 1040 k1) (cons 1040 k2) (cons 1040 k3)
    (cons 1000 unitStr) (cons 1005 visHandle))))
  (entmod (append (entget ent) (list (list -3 (cons "MY_CAE_SPRING" newRecords)))))
  (entupd ent)
  (entmod (append (entget visBlkEnt)
                  (list (list -3 (list "MY_CAE_SPRING"
                    (cons 1005 beamHandle) (cons 1000 endTag) (cons 1000 kindTag))))))
)

;;; 刚度输入：纯字符串逗号分隔（不用 getpoint，避免捕捉坐标）；3 与 6 个数同一方式
(defun split-csv-tokens (s / i c cur out)
  (setq out nil cur "" i 0)
  (repeat (strlen s)
    (setq c (substr s (1+ i) 1))
    (if (or (= c ",") (= c " ") (= c "\t") (= c ";"))
      (progn
        (if (/= cur "") (setq out (append out (list cur)) cur ""))
      )
      (setq cur (strcat cur c))
    )
    (setq i (1+ i))
  )
  (if (/= cur "") (setq out (append out (list cur))))
  out
)

(defun read-k-csv (promptMsg nDefs / s parts vals tok)
  (setq s (getstring T promptMsg))
  (if (or (not s) (= s ""))
    nDefs
    (progn
      (setq parts (split-csv-tokens s) vals nil)
      (foreach tok parts
        (setq vals (append vals (list (atof tok))))
      )
      (while (< (length vals) (length nDefs))
        (setq vals (append vals (list 0.0)))
      )
      vals
    )
  )
)

(defun c:SETSPRING (/ ent entData beamHandle p1 p2 beamLen endInfo ptNode endTag
                      kindChoice kx ky kz krx kry krz unitStr unitRot visBlk vals)
  (register-all-cae-apps)
  (setq ent (car (entsel (_T "\n[第1步] 选择梁直线 (LINE): "
                             "\n[Step 1] Select a beam line (LINE): "))))
  (if (and ent (= (cdr (assoc 0 (setq entData (entget ent)))) "LINE"))
    (progn
      (setq beamHandle (cdr (assoc 5 entData)))
      (setq p1 (cdr (assoc 10 entData)) p2 (cdr (assoc 11 entData)))
      (setq beamLen (distance p1 p2))
      (setq endInfo (pick-beam-end ent))
      (if endInfo
        (progn
          (setq ptNode (car endInfo) endTag (cadr endInfo))
          (initget "Trans Rot Both")
          (setq kindChoice (getkword (_T "\n类型 [Trans/Rot/Both] <Trans>: "
                                         "\nType [Trans/Rot/Both] <Trans>: ")))
          (if (not kindChoice) (setq kindChoice "Trans"))
          (cond
            ((= kindChoice "Trans")
             (setq vals (read-k-csv (_T "\nKx,Ky,Kz <0,0,0>: " "\nKx,Ky,Kz <0,0,0>: ") '(0.0 0.0 0.0)))
             (setq kx (nth 0 vals) ky (nth 1 vals) kz (nth 2 vals))
             (setq unitStr (ask-trans-k-unit))
             (remove-old-spring-visual ent endTag "TRANS")
             (setq visBlk (create-trans-spring-block ptNode beamLen kx ky kz unitStr endTag))
             (write-spring-record ent beamHandle endTag "TRANS" kx ky kz unitStr visBlk)
             (princ (strcat "\n[OK] K[" endTag "]=" (rtos kx 2 2) "," (rtos ky 2 2) "," (rtos kz 2 2) " " unitStr))
            )
            ((= kindChoice "Rot")
             (setq vals (read-k-csv (_T "\nKRx,KRy,KRz <0,0,0>: " "\nKRx,KRy,KRz <0,0,0>: ") '(0.0 0.0 0.0)))
             (setq krx (nth 0 vals) kry (nth 1 vals) krz (nth 2 vals))
             (setq unitStr (ask-rot-k-unit))
             (remove-old-spring-visual ent endTag "ROT")
             (setq visBlk (create-rot-spring-block ptNode beamLen krx kry krz unitStr endTag))
             (write-spring-record ent beamHandle endTag "ROT" krx kry krz unitStr visBlk)
             (princ (strcat "\n[OK] KR[" endTag "]=" (rtos krx 2 2) "," (rtos kry 2 2) "," (rtos krz 2 2) " " unitStr))
            )
            ((= kindChoice "Both")
             (setq vals (read-k-csv
               (_T "\nKx,Ky,Kz,KRx,KRy,KRz <0,0,0,0,0,0>: " "\nKx,Ky,Kz,KRx,KRy,KRz <0,0,0,0,0,0>: ")
               '(0.0 0.0 0.0 0.0 0.0 0.0)))
             (setq kx (nth 0 vals) ky (nth 1 vals) kz (nth 2 vals)
                   krx (nth 3 vals) kry (nth 4 vals) krz (nth 5 vals))
             (setq unitStr (ask-trans-k-unit))
             (setq unitRot (ask-rot-k-unit))
             (remove-old-spring-visual ent endTag "TRANS")
             (setq visBlk (create-trans-spring-block ptNode beamLen kx ky kz unitStr endTag))
             (write-spring-record ent beamHandle endTag "TRANS" kx ky kz unitStr visBlk)
             (remove-old-spring-visual ent endTag "ROT")
             (setq visBlk (create-rot-spring-block ptNode beamLen krx kry krz unitRot endTag))
             (write-spring-record ent beamHandle endTag "ROT" krx kry krz unitRot visBlk)
             (princ (strcat "\n[OK] K=" (rtos kx 2 2) "," (rtos ky 2 2) "," (rtos kz 2 2)
                            " KR=" (rtos krx 2 2) "," (rtos kry 2 2) "," (rtos krz 2 2)))
            )
          )
        )
        (princ (_T "\n[取消] 未捕捉端点。" "\n[Cancel] No endpoint picked."))
      )
    )
    (princ (_T "\n[错误] 请选择 LINE。" "\n[Error] Select a LINE."))
  )
  (princ)
)

(defun c:DELSPRING (/ ss i ent entData entType xdata appData j handle oldBlk
                      targetEnt targetEndTag targetKind oldXdata newRecords)
  (unlock-vis-layer)
  (princ (_T "\n请选择【梁】或【弹性支撑符号】: "
             "\nSelect beam(s) or elastic-spring symbol(s): "))
  (setq ss (ssget '((0 . "LINE,INSERT"))))
  (if ss
    (progn
      (setq i 0)
      (while (< i (sslength ss))
        (setq ent (ssname ss i))
        (setq entData (entget ent '("MY_CAE_SPRING")))
        (setq entType (cdr (assoc 0 entData)))
        (setq xdata (assoc -3 entData))
        (if xdata
          (progn
            (setq appData (cdr (cadr xdata)))
            (cond
              ((= entType "LINE")
               (setq j 0)
               (while (< j (length appData))
                 (setq handle (cdr (nth (+ j 6) appData)))
                 (if (and handle (setq oldBlk (handent handle)))
                   (if (entget oldBlk) (entdel oldBlk))
                 )
                 (setq j (+ j 7))
               )
               (entmod (append (entget ent) (list (list -3 (list "MY_CAE_SPRING")))))
               (entupd ent)
              )
              ((= entType "INSERT")
               (setq targetEnt (handent (cdr (nth 0 appData))))
               (setq targetEndTag (cdr (nth 1 appData)))
               (setq targetKind (cdr (nth 2 appData)))
               (if (and targetEnt (entget targetEnt))
                 (progn
                   (setq oldXdata (assoc -3 (entget targetEnt '("MY_CAE_SPRING"))))
                   (setq newRecords nil)
                   (if oldXdata
                     (setq newRecords (xdata-drop-end-kind (cdr (cadr oldXdata))
                                        targetEndTag targetKind 7))
                   )
                   (if newRecords
                     (entmod (append (entget targetEnt)
                                     (list (list -3 (cons "MY_CAE_SPRING" newRecords)))))
                     (entmod (append (entget targetEnt)
                                     (list (list -3 (list "MY_CAE_SPRING")))))
                   )
                   (entupd targetEnt)
                 )
               )
               (entdel ent)
              )
            )
          )
        )
        (setq i (1+ i))
      )
      (princ (_T "\n[清除完成] 弹性支撑已双向删除。" "\n[Done] Elastic springs removed."))
    )
  )
  (lock-vis-layer)
  (princ)
)

;;; ====================================================================
;;; 复合约束增量  MY_CAE_COMP_BC  （ADDBC）
;;; ====================================================================
(defun merge-constrained-vectors (basisList newVecs / res v)
  (setq res basisList)
  (foreach rawV newVecs
    (if (< (length res) 3)
      (progn
        (setq v (vec-unit rawV))
        (foreach b res
          (setq v (vec-sub v (vec-scale b (vec-dot v b))))
        )
        (if (setq v (vec-unit v))
          (setq res (append res (list v)))
        )
      )
    )
  )
  res
)

(defun build-full-triad (cVecs / n e1 e2 e3 mask)
  (setq n (length cVecs))
  (cond
    ((= n 0) (setq e1 '(1.0 0.0 0.0) e2 '(0.0 1.0 0.0) e3 '(0.0 0.0 1.0) mask "000"))
    ((= n 1)
     (setq e1 (car cVecs) e2 (cadr (make-local-basis e1)))
     (setq e3 (vec-unit (vec-cross e1 e2)) mask "100"))
    ((= n 2)
     (setq e1 (car cVecs) e2 (cadr cVecs))
     (setq e3 (vec-unit (vec-cross e1 e2)) mask "110"))
    (T
     (setq e1 (car cVecs) e2 (cadr cVecs))
     (setq e3 (vec-unit (vec-cross e1 e2)) mask "111"))
  )
  (list e1 e2 e3 mask)
)

;;; 复合约束：同简单 BC
(defun create-comp-bc-block (ptNode beamLen uVecs rVecs uMask rMask endTag /
                             sz r gap stem c2 pL1 pL2 axEnd labelPt labelStr blkDefName blkRef)
  (unlock-vis-layer)
  (setq sz (* beamLen 0.12))
  (if (< sz 100.0) (setq sz 100.0))
  (setq sz (* sz *CAE_SCALE_BC*))
  (setq r (* sz 0.10) gap (* sz 0.08) stem (* sz 0.70))
  (setq c2 (list 0.0 0.0 (- (+ r gap stem r))))
  (setq pL1 (list 0.0 0.0 (- r))
        pL2 (list 0.0 0.0 (+ (caddr c2) r)))
  (entmake (list '(0 . "BLOCK") '(2 . "*U") '(70 . 1) '(10 0.0 0.0 0.0)))
  (entmake (list '(0 . "CIRCLE") '(8 . "0") '(62 . 4) '(10 0.0 0.0 0.0) (cons 40 r) '(210 0.0 0.0 1.0)))
  (entmake (list '(0 . "CIRCLE") '(8 . "0") '(62 . 4) (cons 10 c2) (cons 40 r) '(210 0.0 0.0 1.0)))
  (entmake (list '(0 . "LINE") '(8 . "0") '(62 . 4) (cons 10 pL1) (cons 11 pL2)))
  (foreach u uVecs
    (setq axEnd (vec-add c2 (vec-scale u (* sz 0.55))))
    (entmake (list '(0 . "LINE") '(8 . "0") '(62 . 6) (cons 10 c2) (cons 11 axEnd)))
  )
  (foreach rr rVecs
    (setq axEnd (vec-add c2 (vec-scale rr (* sz 0.70))))
    (entmake (list '(0 . "LINE") '(8 . "0") '(62 . 2) (cons 10 c2) (cons 11 axEnd)))
  )
  (setq labelPt (list (* sz 0.05) (* sz 0.05) (- (+ r gap stem r (* sz 0.15)))))
  (setq labelStr (strcat "BC[" endTag "] U:" uMask " R:" rMask))
  (entmake (list '(0 . "TEXT") '(8 . "0") '(62 . 4) (cons 10 labelPt) (cons 40 (* sz 0.20)) (cons 1 labelStr)))
  (setq blkDefName (entmake '((0 . "ENDBLK"))))
  (setq blkRef (entmakex (list '(0 . "INSERT") '(8 . "CAE_VIS_BC") (cons 2 blkDefName) (cons 10 ptNode))))
  (lock-vis-layer)
  blkRef
)

(defun get-existing-comp-bc (beamEnt targetEndTag / entData xdata appData i uMask rMask uVecs rVecs res)
  (setq entData (entget beamEnt '("MY_CAE_COMP_BC")))
  (setq xdata (assoc -3 entData) res (list nil nil nil))
  (if xdata
    (progn
      (setq appData (cdr (cadr xdata)) i 0)
      (while (< i (length appData))
        (if (= (cdr (nth i appData)) targetEndTag)
          (progn
            (setq uMask (cdr (nth (+ i 1) appData)))
            (setq rMask (cdr (nth (+ i 5) appData)))
            (setq uVecs nil rVecs nil)
            (if (>= (atoi (substr uMask 1 1)) 1) (setq uVecs (append uVecs (list (cdr (nth (+ i 2) appData))))))
            (if (>= (atoi (substr uMask 2 1)) 1) (setq uVecs (append uVecs (list (cdr (nth (+ i 3) appData))))))
            (if (>= (atoi (substr uMask 3 1)) 1) (setq uVecs (append uVecs (list (cdr (nth (+ i 4) appData))))))
            (if (>= (atoi (substr rMask 1 1)) 1) (setq rVecs (append rVecs (list (cdr (nth (+ i 6) appData))))))
            (if (>= (atoi (substr rMask 2 1)) 1) (setq rVecs (append rVecs (list (cdr (nth (+ i 7) appData))))))
            (if (>= (atoi (substr rMask 3 1)) 1) (setq rVecs (append rVecs (list (cdr (nth (+ i 8) appData))))))
            (setq res (list uVecs rVecs (cdr (nth (+ i 9) appData))))
          )
        )
        (setq i (+ i 10))
      )
    )
  )
  res
)

(defun c:ADDBC (/ ent entData beamHandle p1 p2 beamLen endInfo ptNode endTag existing uVecs rVecs oldHandle oldBlk addType pA pB v1 v2 nVec sVec rotOpt rAxis uTriad rTriad visBlkEnt visHandle oldXdata newRecords)
  (register-all-cae-apps)
  (setq ent (car (entsel (_T "\n[第1步] 选择要叠加约束的梁 (LINE): " "\n[Step 1] Select beam to add BC (LINE): "))))
  (if (and ent (= (cdr (assoc 0 (setq entData (entget ent)))) "LINE"))
    (progn
      (setq beamHandle (cdr (assoc 5 entData)))
      (setq p1 (cdr (assoc 10 entData)) p2 (cdr (assoc 11 entData)))
      (setq beamLen (distance p1 p2))
      (setq endInfo (pick-beam-end ent))
      (if endInfo
        (progn
          (setq ptNode (car endInfo) endTag (cadr endInfo))
          (remove-old-bc-visual ent endTag)
          (setq existing (get-existing-comp-bc ent endTag))
          (setq uVecs (car existing) rVecs (cadr existing) oldHandle (caddr existing))
          (initget "Plane Slide RotAxis FixAll")
          (setq addType (getkword (strcat (_T "\n" "\n") endTag " U:" (itoa (length uVecs))
                                          " R:" (itoa (length rVecs))
                                          (_T " [Plane/Slide/RotAxis/FixAll] <Plane>: "
                                              " [Plane/Slide/RotAxis/FixAll] <Plane>: "))))
          (if (not addType) (setq addType "Plane"))
          (cond
            ((= addType "Plane")
             (setq pA (getpoint (_T "\n平面内第2点: " "\n2nd point in plane: ")))
             (if pA (setq pB (getpoint (_T "\n平面内第3点: " "\n3rd point in plane: "))))
             (if (and pA pB)
               (progn
                 (setq nVec (vec-unit (vec-cross
                   (vec-sub (trans pA 1 0) ptNode)
                   (vec-sub (trans pB 1 0) ptNode))))
                 (if nVec
                   (setq uVecs (merge-constrained-vectors uVecs (list nVec)))
                   (princ (_T "\n[错误] 三点共线。" "\n[Error] Three points are colinear."))
                 )
               )
             )
            )
            ((= addType "Slide")
             (setq pA (getpoint (_T "\n滑移线上第2点: " "\n2nd point on slide line: ")))
             (if pA
               (progn
                 (setq sVec (vec-unit (vec-sub (trans pA 1 0) ptNode)))
                 (if sVec
                   (progn
                     (setq uTriad (make-local-basis sVec))
                     (setq uVecs (merge-constrained-vectors uVecs (list (cadr uTriad) (caddr uTriad))))
                   )
                 )
               )
             )
            )
            ((= addType "RotAxis")
             (initget "BeamAxis PickLine")
             (setq rotOpt (getkword (_T "\n旋转轴 [BeamAxis/PickLine] <BeamAxis>: " "\nRotation axis [BeamAxis/PickLine] <BeamAxis>: ")))
             (if (not rotOpt) (setq rotOpt "BeamAxis"))
             (if (= rotOpt "BeamAxis")
               (setq rAxis (vec-unit (vec-sub p2 p1)))
               (progn
                 (setq pA (getpoint (_T "\n旋转轴上第2点: " "\n2nd point on rotation axis: ")))
                 (if pA (setq rAxis (vec-unit (vec-sub (trans pA 1 0) ptNode))))
               )
             )
             (if rAxis
               (setq rVecs (merge-constrained-vectors rVecs (list rAxis)))
               (princ (_T "\n[错误] 旋转轴无效。" "\n[Error] Invalid rotation axis."))
             )
            )
            ((= addType "FixAll")
             (setq uVecs '((1.0 0.0 0.0) (0.0 1.0 0.0) (0.0 0.0 1.0)))
             (setq rVecs '((1.0 0.0 0.0) (0.0 1.0 0.0) (0.0 0.0 1.0)))
            )
          )
          (if (and oldHandle (= (type oldHandle) 'STR))
            (progn
              (setq oldBlk (handent oldHandle))
              (if (and oldBlk (entget oldBlk))
                (progn (unlock-vis-layer) (entdel oldBlk) (lock-vis-layer))
              )
            )
          )
          (setq uTriad (build-full-triad uVecs) rTriad (build-full-triad rVecs))
          (setq visBlkEnt (create-comp-bc-block ptNode beamLen uVecs rVecs
                            (nth 3 uTriad) (nth 3 rTriad) endTag))
          (setq visHandle (cdr (assoc 5 (entget visBlkEnt))))
          (setq oldXdata (assoc -3 (entget ent '("MY_CAE_COMP_BC"))))
          (setq newRecords nil)
          (if oldXdata
            (setq newRecords (xdata-drop-end (cdr (cadr oldXdata)) endTag 10))
          )
          (setq newRecords (append newRecords (list
            (cons 1000 endTag)
            (cons 1000 (nth 3 uTriad))
            (cons 1013 (nth 0 uTriad)) (cons 1013 (nth 1 uTriad)) (cons 1013 (nth 2 uTriad))
            (cons 1000 (nth 3 rTriad))
            (cons 1013 (nth 0 rTriad)) (cons 1013 (nth 1 rTriad)) (cons 1013 (nth 2 rTriad))
            (cons 1005 visHandle))))
          (entmod (append (entget ent) (list (list -3 (cons "MY_CAE_COMP_BC" newRecords)))))
          (entupd ent)
          (entmod (append (entget visBlkEnt)
                          (list (list -3 (list "MY_CAE_COMP_BC"
                            (cons 1005 beamHandle) (cons 1000 endTag))))))
          (princ (strcat (_T "\n[合成成功] [" "\n[Combined OK] [") endTag "] U:" (nth 3 uTriad) " R:" (nth 3 rTriad)))
        )
      )
    )
  )
  (princ)
)

;;; ====================================================================
;;; 截面 / 材质  MY_CAE_SEC
;;; ====================================================================
(defun create-sec-block (ent secType secSpec matName vy vz offsetVec / entData p1 p2 midPt beamLen sz pyEnd pzEnd offEnd labelPt labelStr blkDefName blkRef)
  (cae-vis-unlock)
  (setq entData (entget ent))
  (setq p1 (cdr (assoc 10 entData)) p2 (cdr (assoc 11 entData)))
  (setq midPt (vec-scale (vec-add p1 p2) 0.5) beamLen (distance p1 p2))
  (setq sz (* beamLen 0.11))
  (if (< sz 100.0) (setq sz 100.0))
  (setq sz (* sz *CAE_SCALE_SEC*))
  (entmake (list '(0 . "BLOCK") '(2 . "*U") '(70 . 1) '(10 0.0 0.0 0.0)))
  (setq pyEnd (vec-scale vy (* sz 1.4)))
  (entmake (list '(0 . "LINE") '(8 . "0") '(62 . 6) '(10 0.0 0.0 0.0) (cons 11 pyEnd)))
  (entmake (list '(0 . "CIRCLE") '(8 . "0") '(62 . 6) (cons 10 pyEnd) (cons 40 (* sz 0.12))))
  (setq pzEnd (vec-scale vz (* sz 0.9)))
  (entmake (list '(0 . "LINE") '(8 . "0") '(62 . 30) '(10 0.0 0.0 0.0) (cons 11 pzEnd)))
  (if (> (distance '(0.0 0.0 0.0) offsetVec) 1e-4)
    (progn
      (setq offEnd (vec-scale (vec-unit offsetVec) (* sz 0.8)))
      (entmake (list '(0 . "LINE") '(8 . "0") '(62 . 2) '(10 0.0 0.0 0.0) (cons 11 offEnd)))
      (entmake (list '(0 . "CIRCLE") '(8 . "0") '(62 . 2) (cons 10 offEnd) (cons 40 (* sz 0.08))))
    )
  )
  (setq labelPt (vec-add pyEnd (vec-scale vz (* sz 0.2))))
  (setq labelStr (strcat "[" secType "]" secSpec " (" matName ")"))
  (entmake (list '(0 . "TEXT") '(8 . "0") '(62 . 6) (cons 10 labelPt) (cons 40 (* sz 0.22)) (cons 1 labelStr)))
  (setq blkDefName (entmake '((0 . "ENDBLK"))))
  (setq blkRef (entmakex (list '(0 . "INSERT") '(8 . "CAE_VIS_SEC") (cons 2 blkDefName) (cons 10 midPt))))
  (cae-vis-lock)
  blkRef
)

(defun remove-old-sec-visual (beamEnt / entData xdata appData handle oldBlk)
  (setq entData (entget beamEnt '("MY_CAE_SEC")))
  (setq xdata (assoc -3 entData))
  (if xdata
    (progn
      (setq appData (cdr (cadr xdata)))
      (if (> (length appData) 6)
        (progn
          (setq handle (cdr (nth 6 appData)))
          (if (and handle (setq oldBlk (handent handle)))
            (if (entget oldBlk)
              (progn (cae-vis-unlock) (entdel oldBlk) (cae-vis-lock))
            )
          )
        )
      )
    )
  )
)

(defun c:SETSEC (/ ss typeChoice secType secSpec matChoice matName dirPt needOrient offChoice offPt offDist
                    i beamEnt beamHandle entData p1 p2 ex vy vz basis offUnit offsetVec visBlkEnt visHandle validCount doOffset)
  (register-all-cae-apps)
  (princ (_T "\n请选择梁直线 (支持框选): " "\nSelect beam lines (window OK): "))
  (setq ss (ssget '((0 . "LINE"))))
  (if ss
    (progn
      ;; initget 大写字母为缩写；原 Channel/Circle/Custom 同属 C、Rect/RectTube 同属 R，会串选
      ;; 缩写：A=Angle H=Channel I=IBeam P=Pipe T=RectTube C=Circle R=Rect M=Custom
      (initget "Angle cHannel IBeam Pipe rTube Circle Rect custoM")
      (setq typeChoice (getkword (_T "\n截面类型 [Angle/cHannel/IBeam/Pipe/rTube/Circle/Rect/custoM] <IBeam>: "
                                "\nSection type [Angle/cHannel/IBeam/Pipe/rTube/Circle/Rect/custoM] <IBeam>: ")))
      (if (not typeChoice) (setq typeChoice "IBeam"))
      (setq secType
        (cond
          ((= typeChoice "cHannel") "Channel")
          ((= typeChoice "rTube")   "RectTube")
          ((= typeChoice "custoM")  "Custom")
          (T typeChoice)
        ))
      (cond
        ((= secType "Angle")    (setq secSpec (getstring T (_T "\n角钢型号 <L100x10>: " "\nAngle size <L100x10>: "))) (if (= secSpec "") (setq secSpec "L100x10")))
        ((= secType "Channel")  (setq secSpec (getstring T (_T "\n槽钢型号 <[20a>: " "\nChannel size <[20a>: "))) (if (= secSpec "") (setq secSpec "[20a")))
        ((= secType "IBeam")    (setq secSpec (getstring T (_T "\n工字钢/H型钢 <HM200x150x6x9>: " "\nI/H beam size <HM200x150x6x9>: "))) (if (= secSpec "") (setq secSpec "HM200x150x6x9")))
        ((= secType "Pipe")     (setq secSpec (getstring T (_T "\n圆管 外径x壁厚 <D114x4.5>: " "\nPipe OD x thickness <D114x4.5>: "))) (if (= secSpec "") (setq secSpec "D114x4.5")))
        ((= secType "RectTube") (setq secSpec (getstring T (_T "\n矩形管 高x宽x壁厚 <150x100x5>: " "\nRect tube HxWxT <150x100x5>: "))) (if (= secSpec "") (setq secSpec "150x100x5")))
        ((= secType "Circle")   (setq secSpec (getstring T (_T "\n实心圆直径 <D50>: " "\nSolid circle diameter <D50>: "))) (if (= secSpec "") (setq secSpec "D50")))
        ((= secType "Rect")     (setq secSpec (getstring T (_T "\n实心矩形高x宽 <200x100>: " "\nSolid rect HxW <200x100>: "))) (if (= secSpec "") (setq secSpec "200x100")))
        ((= secType "Custom")   (setq secSpec (getstring T (_T "\n自定义参数 <Custom_Sec>: " "\nCustom params <Custom_Sec>: "))) (if (= secSpec "") (setq secSpec "Custom_Sec")))
      )
      ;; Q235B/Q355B 首字母同为 Q，需输入 Q2/Q3（或全名）区分
      (initget "Q235B Q355B 45Steel Al6061 Concrete Other")
      (setq matChoice (getkword (_T "\n材料 [Q235B/Q355B/45Steel/Al6061/Concrete/Other] <Q355B>: "
                               "\nMaterial [Q235B/Q355B/45Steel/Al6061/Concrete/Other] <Q355B>: ")))
      (if (not matChoice) (setq matChoice "Q355B"))
      (if (= matChoice "Other")
        (progn
          (setq matName (getstring T (_T "\n自定义材料名: " "\nCustom material name: ")))
          (if (= matName "") (setq matName "Custom_Mat"))
        )
        (setq matName matChoice)
      )
      ;; Pipe / Circle：绕轴对称无需姿态；杆(ROD)在每根实体上忽略姿态/偏置
      (setq needOrient (not (member secType '("Pipe" "Circle")))
            dirPt nil)
      (if needOrient
        (progn
          (setq dirPt (getpoint (_T "\n[姿态] 不在梁上的一点 → 截面 Y 轴 (杆忽略): "
                               "\n[Orientation] Point off beam → Y (ignored for ROD): ")))
          (if dirPt (setq dirPt (trans dirPt 1 0)))
        )
      )
      (if (or (not needOrient) dirPt)
        (progn
          (initget "Yes No")
          (setq offChoice (getkword (_T "\n是否设置梁偏置? (杆忽略) [Yes/No] <No>: "
                                        "\nSet beam offset? (ignored for ROD) [Yes/No] <No>: ")))
          (if (not offChoice) (setq offChoice "No"))
          (setq doOffset (= offChoice "Yes")
                offPt nil
                offDist 0.0
                offsetVec '(0.0 0.0 0.0))
          (if doOffset
            (progn
              (setq offPt (getpoint (_T "\n[偏置] 不在梁上的一点 → 偏置方向: "
                                   "\n[Offset] Point off beam → offset direction: ")))
              (if offPt
                (progn
                  (setq offPt (trans offPt 1 0))
                  (setq offDist (getreal (_T "\n偏置距离 (mm) <0.0>: "
                                            "\nOffset distance (mm) <0.0>: ")))
                  (if (not offDist) (setq offDist 0.0))
                )
                (progn
                  (setq doOffset nil)
                  (princ (_T "\n[提示] 未指定偏置点，按无偏置继续。"
                             "\n[Note] No offset point; continuing with zero offset."))
                )
              )
            )
          )
          (setq i 0 validCount 0)
          (cae-vis-begin-batch)
          (while (< i (sslength ss))
            (setq beamEnt (ssname ss i))
            (setq entData (entget beamEnt))
            (setq beamHandle (cdr (assoc 5 entData)))
            (setq p1 (cdr (assoc 10 entData)) p2 (cdr (assoc 11 entData)))
            (setq ex (vec-unit (vec-sub p2 p1)))
            ;; 杆：只写截面尺寸+材料，姿态/偏置强制为零基（解析端也会忽略）
            (if (or (cae-is-rod beamEnt) (member secType '("Pipe" "Circle")))
              (progn
                (setq basis (make-local-basis ex))
                (setq vy (cadr basis) vz (caddr basis)
                      offsetVec '(0.0 0.0 0.0) offUnit '(0.0 0.0 0.0))
              )
              (progn
                (setq vy (get-perp-unit-vec p1 p2 dirPt))
                (setq vz (if (and ex vy) (vec-unit (vec-cross ex vy)) nil))
                (setq offUnit (if (and doOffset offPt)
                                (get-perp-unit-vec p1 p2 offPt)
                                '(0.0 0.0 0.0)))
                (setq offsetVec (if (and doOffset offUnit (not (cae-is-rod beamEnt)))
                                  (vec-scale offUnit offDist)
                                  '(0.0 0.0 0.0)))
              )
            )
            (if (and ex vy vz (or (cae-is-rod beamEnt) (not doOffset) offUnit))
              (progn
                ;; 一根线只保留一个截面：先删旧符号并清空 MY_CAE_SEC，再写入这一条
                (remove-old-sec-visual beamEnt)
                (entmod (append (entget beamEnt) '((-3 ("MY_CAE_SEC")))))
                (setq visBlkEnt (create-sec-block beamEnt secType secSpec matName vy vz offsetVec))
                (setq visHandle (cdr (assoc 5 (entget visBlkEnt))))
                (entmod (append (entget beamEnt)
                                (list (list -3 (list "MY_CAE_SEC"
                                  (cons 1000 secType) (cons 1000 secSpec) (cons 1000 matName)
                                  (cons 1013 vy) (cons 1013 vz) (cons 1013 offsetVec)
                                  (cons 1005 visHandle))))))
                (entupd beamEnt)
                (entmod (append (entget visBlkEnt)
                                (list (list -3 (list "MY_CAE_SEC" (cons 1005 beamHandle))))))
                (setq validCount (1+ validCount))
              )
              (princ (strcat (_T "\n[跳过] " "\n[Skip] ") beamHandle (_T " 与参考点共线。" " colinear with reference point.")))
            )
            (setq i (1+ i))
          )
          (cae-vis-end-batch)
          (princ (strcat (_T "\n[成功] " "\n[OK] ") (itoa validCount) (_T " 根梁 [" " beam(s) [") secType ":" secSpec "] / " matName))
        )
        (princ (_T "\n[取消] 未指定姿态点。" "\n[Cancel] Orientation point not specified."))
      )
    )
    (princ (_T "\n[取消] 未选中直线。" "\n[Cancel] No lines selected."))
  )
  (princ)
)

(defun c:DELSEC (/ ss i ent entData entType xdata appData oldBlk targetEnt)
  (unlock-vis-layer)
  (princ (_T "\n请选择【梁】或【截面符号】: " "\nSelect beam(s) or section symbol(s): "))
  (setq ss (ssget '((0 . "LINE,INSERT"))))
  (if ss
    (progn
      (setq i 0)
      (while (< i (sslength ss))
        (setq ent (ssname ss i))
        (setq entData (entget ent '("MY_CAE_SEC")))
        (setq entType (cdr (assoc 0 entData)))
        (setq xdata (assoc -3 entData))
        (if xdata
          (progn
            (setq appData (cdr (cadr xdata)))
            (if (= entType "LINE")
              (progn
                (if (> (length appData) 6)
                  (if (setq oldBlk (handent (cdr (nth 6 appData))))
                    (if (entget oldBlk) (entdel oldBlk))
                  )
                )
                (entmod (append (entget ent) (list (list -3 (list "MY_CAE_SEC")))))
                (entupd ent)
              )
              (progn
                (setq targetEnt (handent (cdr (nth 0 appData))))
                (if (and targetEnt (entget targetEnt))
                  (progn
                    (entmod (append (entget targetEnt) (list (list -3 (list "MY_CAE_SEC")))))
                    (entupd targetEnt)
                  )
                )
                (entdel ent)
              )
            )
          )
        )
        (setq i (1+ i))
      )
      (princ (_T "\n[清除完成] 截面属性已双向删除。" "\n[Done] Section data removed."))
    )
  )
  (lock-vis-layer)
  (princ)
)

;;; ====================================================================
;;; 全图刷新
;;; ====================================================================
(defun refresh-dist-loads (/ ss i ent beamHandle entData xdata appData loadMag unitStr unitVec visBlkEnt visHandle count)
  (setq count 0 ss (ssget "_X" '((0 . "LINE") (-3 ("MY_CAE_LOAD")))))
  (if ss
    (progn
      (setq i 0)
      (while (< i (sslength ss))
        (setq ent (ssname ss i) beamHandle (cdr (assoc 5 (entget ent))))
        (setq entData (entget ent '("MY_CAE_LOAD")) xdata (assoc -3 entData))
        (if xdata
          (progn
            (setq appData (cdr (cadr xdata)))
            (setq loadMag (cdr (nth 1 appData))
                  unitStr (cdr (nth 2 appData))
                  unitVec (cdr (nth 3 appData)))
            (setq unitStr (normalize-dist-unit unitStr))
            (setq visBlkEnt (create-load-block ent loadMag unitVec unitStr))
            (setq visHandle (cdr (assoc 5 (entget visBlkEnt))))
            (entmod (append (entget ent) (list (list -3 (list "MY_CAE_LOAD"
              (cons 1000 "Distributed") (cons 1040 loadMag) (cons 1000 unitStr)
              (cons 1013 unitVec) (cons 1005 visHandle))))))
            (entmod (append (entget visBlkEnt) (list (list -3 (list "MY_CAE_LOAD" (cons 1005 beamHandle))))))
            (setq count (1+ count))
          )
        )
        (setq i (1+ i))
      )
    )
  )
  count
)

(defun refresh-point-loads (/ ss i ent entData beamHandle p1 p2 beamLen xdata appData j stride endTag forceMag unitVec unitStr ptNode visBlkEnt visHandle newRecords count)
  (setq count 0 ss (ssget "_X" '((0 . "LINE") (-3 ("MY_CAE_POINT_LOAD")))))
  (if ss
    (progn
      (setq i 0)
      (while (< i (sslength ss))
        (setq ent (ssname ss i) entData (entget ent '("MY_CAE_POINT_LOAD")))
        (setq beamHandle (cdr (assoc 5 entData)))
        (setq p1 (cdr (assoc 10 entData)) p2 (cdr (assoc 11 entData)) beamLen (distance p1 p2))
        (setq xdata (assoc -3 entData))
        (if xdata
          (progn
            (setq appData (cdr (cadr xdata)) newRecords nil j 0 stride (ptload-stride appData))
            (while (< j (length appData))
              (setq endTag (cdr (nth j appData))
                    forceMag (cdr (nth (+ j 1) appData))
                    unitVec (cdr (nth (+ j 2) appData))
                    unitStr (if (= stride 5) (cdr (nth (+ j 4) appData)) "N")
                    ptNode (if (= endTag "START") p1 p2))
              (if (or (not unitStr) (/= (type unitStr) 'STR) (= unitStr "START") (= unitStr "END"))
                (setq unitStr "N")
              )
              (setq visBlkEnt (create-ptload-block ptNode beamLen forceMag unitVec endTag unitStr))
              (setq visHandle (cdr (assoc 5 (entget visBlkEnt))))
              (entmod (append (entget visBlkEnt) (list (list -3 (list "MY_CAE_POINT_LOAD"
                (cons 1005 beamHandle) (cons 1000 endTag))))))
              (setq newRecords (append newRecords (list
                (cons 1000 endTag) (cons 1040 forceMag) (cons 1013 unitVec)
                (cons 1005 visHandle) (cons 1000 unitStr))))
              (setq count (1+ count) j (+ j stride))
            )
            (entmod (append (entget ent) (list (list -3 (cons "MY_CAE_POINT_LOAD" newRecords)))))
            (entupd ent)
          )
        )
        (setq i (1+ i))
      )
    )
  )
  count
)

(defun refresh-moment-loads (/ ss i ent entData beamHandle p1 p2 beamLen xdata appData j
                               endTag momMag axisVec unitStr ptNode visBlkEnt visHandle
                               newRecords count)
  (setq count 0 ss (ssget "_X" '((0 . "LINE") (-3 ("MY_CAE_MOMENT")))))
  (if ss
    (progn
      (setq i 0)
      (while (< i (sslength ss))
        (setq ent (ssname ss i) entData (entget ent '("MY_CAE_MOMENT")))
        (setq beamHandle (cdr (assoc 5 entData)))
        (setq p1 (cdr (assoc 10 entData)) p2 (cdr (assoc 11 entData)) beamLen (distance p1 p2))
        (setq xdata (assoc -3 entData))
        (if xdata
          (progn
            (setq appData (cdr (cadr xdata)) newRecords nil j 0)
            (while (< j (length appData))
              (setq endTag (cdr (nth j appData))
                    momMag (cdr (nth (+ j 1) appData))
                    axisVec (cdr (nth (+ j 2) appData))
                    unitStr (cdr (nth (+ j 4) appData))
                    ptNode (if (= endTag "START") p1 p2))
              (if (or (not unitStr) (/= (type unitStr) 'STR)) (setq unitStr "Nmm"))
              ;; 轴已含转向符号，统一按 CCW 绘制
              (setq visBlkEnt (create-moment-block ptNode beamLen momMag axisVec endTag unitStr "CCW"))
              (setq visHandle (cdr (assoc 5 (entget visBlkEnt))))
              (entmod (append (entget visBlkEnt) (list (list -3 (list "MY_CAE_MOMENT"
                (cons 1005 beamHandle) (cons 1000 endTag))))))
              (setq newRecords (append newRecords (list
                (cons 1000 endTag) (cons 1040 momMag) (cons 1013 axisVec)
                (cons 1005 visHandle) (cons 1000 unitStr))))
              (setq count (1+ count) j (+ j 5))
            )
            (entmod (append (entget ent) (list (list -3 (cons "MY_CAE_MOMENT" newRecords)))))
            (entupd ent)
          )
        )
        (setq i (1+ i))
      )
    )
  )
  count
)

(defun refresh-simple-bcs (/ ss i ent entData beamHandle p1 p2 beamLen xdata appData j endTag bcMode maskStr e1 e2 ptNode visBlkEnt visHandle newRecords basis count)
  (setq count 0 ss (ssget "_X" '((0 . "LINE") (-3 ("MY_CAE_BC")))))
  (if ss
    (progn
      (setq i 0)
      (while (< i (sslength ss))
        (setq ent (ssname ss i) entData (entget ent '("MY_CAE_BC")))
        (setq beamHandle (cdr (assoc 5 entData)))
        (setq p1 (cdr (assoc 10 entData)) p2 (cdr (assoc 11 entData)) beamLen (distance p1 p2))
        (setq xdata (assoc -3 entData))
        (if xdata
          (progn
            (setq appData (cdr (cadr xdata)) newRecords nil j 0)
            (while (< j (length appData))
              (setq endTag (cdr (nth j appData))
                    bcMode (cdr (nth (+ j 1) appData))
                    maskStr (cdr (nth (+ j 2) appData))
                    e1 (cdr (nth (+ j 3) appData))
                    e2 (cdr (nth (+ j 4) appData))
                    ptNode (if (= endTag "START") p1 p2))
              (setq basis (make-local-basis e1))
              (setq visBlkEnt (create-bc-block ptNode beamLen bcMode maskStr e1 e2 (caddr basis) endTag))
              (setq visHandle (cdr (assoc 5 (entget visBlkEnt))))
              (entmod (append (entget visBlkEnt) (list (list -3 (list "MY_CAE_BC"
                (cons 1005 beamHandle) (cons 1000 endTag))))))
              (setq newRecords (append newRecords (list
                (cons 1000 endTag) (cons 1000 bcMode) (cons 1000 maskStr)
                (cons 1013 e1) (cons 1013 e2) (cons 1005 visHandle))))
              (setq count (1+ count) j (+ j 6))
            )
            (entmod (append (entget ent) (list (list -3 (cons "MY_CAE_BC" newRecords)))))
            (entupd ent)
          )
        )
        (setq i (1+ i))
      )
    )
  )
  count
)

(defun refresh-comp-bcs (/ ss i ent entData beamHandle p1 p2 beamLen xdata appData j endTag uMask rMask uVecs rVecs ptNode visBlkEnt visHandle newRecords count)
  (setq count 0 ss (ssget "_X" '((0 . "LINE") (-3 ("MY_CAE_COMP_BC")))))
  (if ss
    (progn
      (setq i 0)
      (while (< i (sslength ss))
        (setq ent (ssname ss i) entData (entget ent '("MY_CAE_COMP_BC")))
        (setq beamHandle (cdr (assoc 5 entData)))
        (setq p1 (cdr (assoc 10 entData)) p2 (cdr (assoc 11 entData)) beamLen (distance p1 p2))
        (setq xdata (assoc -3 entData))
        (if xdata
          (progn
            (setq appData (cdr (cadr xdata)) newRecords nil j 0)
            (while (< j (length appData))
              (setq endTag (cdr (nth j appData))
                    uMask (cdr (nth (+ j 1) appData))
                    rMask (cdr (nth (+ j 5) appData))
                    uVecs nil rVecs nil)
              (if (>= (atoi (substr uMask 1 1)) 1) (setq uVecs (append uVecs (list (cdr (nth (+ j 2) appData))))))
              (if (>= (atoi (substr uMask 2 1)) 1) (setq uVecs (append uVecs (list (cdr (nth (+ j 3) appData))))))
              (if (>= (atoi (substr uMask 3 1)) 1) (setq uVecs (append uVecs (list (cdr (nth (+ j 4) appData))))))
              (if (>= (atoi (substr rMask 1 1)) 1) (setq rVecs (append rVecs (list (cdr (nth (+ j 6) appData))))))
              (if (>= (atoi (substr rMask 2 1)) 1) (setq rVecs (append rVecs (list (cdr (nth (+ j 7) appData))))))
              (if (>= (atoi (substr rMask 3 1)) 1) (setq rVecs (append rVecs (list (cdr (nth (+ j 8) appData))))))
              (setq ptNode (if (= endTag "START") p1 p2))
              (setq visBlkEnt (create-comp-bc-block ptNode beamLen uVecs rVecs uMask rMask endTag))
              (setq visHandle (cdr (assoc 5 (entget visBlkEnt))))
              (entmod (append (entget visBlkEnt) (list (list -3 (list "MY_CAE_COMP_BC"
                (cons 1005 beamHandle) (cons 1000 endTag))))))
              (setq newRecords (append newRecords (list
                (nth j appData) (nth (+ j 1) appData) (nth (+ j 2) appData)
                (nth (+ j 3) appData) (nth (+ j 4) appData) (nth (+ j 5) appData)
                (nth (+ j 6) appData) (nth (+ j 7) appData) (nth (+ j 8) appData)
                (cons 1005 visHandle))))
              (setq count (1+ count) j (+ j 10))
            )
            (entmod (append (entget ent) (list (list -3 (cons "MY_CAE_COMP_BC" newRecords)))))
            (entupd ent)
          )
        )
        (setq i (1+ i))
      )
    )
  )
  count
)

(defun refresh-sections (/ ss i ent entData beamHandle xdata appData secType secSpec matName vy vz offsetVec visBlkEnt visHandle count)
  (setq count 0 ss (ssget "_X" '((0 . "LINE") (-3 ("MY_CAE_SEC")))))
  (if ss
    (progn
      (setq i 0)
      (cae-vis-begin-batch)
      (while (< i (sslength ss))
        (setq ent (ssname ss i) entData (entget ent '("MY_CAE_SEC")))
        (setq beamHandle (cdr (assoc 5 entData)) xdata (assoc -3 entData))
        (if xdata
          (progn
            (setq appData (cdr (cadr xdata)))
            (setq secType (cdr (nth 0 appData)) secSpec (cdr (nth 1 appData))
                  matName (cdr (nth 2 appData)) vy (cdr (nth 3 appData))
                  vz (cdr (nth 4 appData)) offsetVec (cdr (nth 5 appData)))
            (setq visBlkEnt (create-sec-block ent secType secSpec matName vy vz offsetVec))
            (setq visHandle (cdr (assoc 5 (entget visBlkEnt))))
            (entmod (append (entget ent) (list (list -3 (list "MY_CAE_SEC"
              (cons 1000 secType) (cons 1000 secSpec) (cons 1000 matName)
              (cons 1013 vy) (cons 1013 vz) (cons 1013 offsetVec)
              (cons 1005 visHandle))))))
            (entupd ent)
            (entmod (append (entget visBlkEnt) (list (list -3 (list "MY_CAE_SEC" (cons 1005 beamHandle))))))
            (setq count (1+ count))
          )
        )
        (setq i (1+ i))
      )
      (cae-vis-end-batch)
    )
  )
  count
)

;;; ---------- 板壳刷新（与梁共用 *CAE_SCALE_* 与 CAE_VIS_* 图层）----------
(defun refresh-shell-loads (/ ss i ent entHandle entData xdata appData idx newRecs
                             loadType lc mag unitStr unitVec normalP numPts headLen pts j
                             info cenPt diagLen loadTypeTag visBlk visHandle count dirCode)
  (vl-load-com)
  (setq count 0
        ss (ssget "_X" (list (cons 0 (cae-shell-type-filter))
                             '(-3 ("MY_CAE_SHELL_LOAD")))))
  (if ss
    (progn
      (setq i 0)
      (while (< i (sslength ss))
        (setq ent (ssname ss i)
              entData (entget ent '("MY_CAE_SHELL_LOAD"))
              entHandle (cdr (assoc 5 entData))
              xdata (assoc -3 entData))
        (if xdata
          (progn
            (setq appData (cdr (cadr xdata)) newRecs nil idx 0)
            (while (< idx (length appData))
              (setq loadType (cdr (nth idx appData))
                    lc (cdr (nth (+ idx 1) appData))
                    mag (cdr (nth (+ idx 2) appData)))
              (if (= (type (cdr (nth (+ idx 3) appData))) 'STR)
                (progn
                  (setq unitStr (cdr (nth (+ idx 3) appData))
                        normalP (and (= (type (cdr (nth (+ idx 4) appData))) 'STR)
                                     (= (strcase (cdr (nth (+ idx 4) appData))) "NORMAL"))
                        unitVec (if normalP nil (cdr (nth (+ idx 4) appData)))
                        numPts (cdr (nth (+ idx 6) appData))
                        headLen 7)
                )
                (progn
                  (setq unitVec (cdr (nth (+ idx 3) appData))
                        normalP nil
                        numPts (cdr (nth (+ idx 5) appData))
                        headLen 6
                        unitStr (cond
                                  ((= loadType "EDGE_LOAD") "N-mm")
                                  ((= loadType "FACE_TOTAL_FORCE") "N")
                                  (T "MPa")))
                )
              )
              (setq pts nil j 0)
              (while (< j numPts)
                (setq pts (append pts (list (cdr (nth (+ idx headLen j) appData)))))
                (setq j (1+ j))
              )
              (cond
                ((= loadType "EDGE_LOAD")
                 (if (and pts unitVec)
                   (progn
                     (setq visBlk (create-shell-edgeload-block pts mag unitVec unitStr))
                     (setq visHandle (cdr (assoc 5 (entget visBlk))))
                     (entmod (append (entget visBlk)
                                     (list (list -3 (list "MY_CAE_SHELL_LOAD" (cons 1005 entHandle))))))
                     (setq newRecs (append newRecs
                       (list (cons 1000 loadType) (cons 1000 lc) (cons 1040 mag)
                             (cons 1000 unitStr) (cons 1013 unitVec)
                             (cons 1005 visHandle) (cons 1070 (length pts)))
                       (mapcar '(lambda (p) (cons 1010 p)) pts)))
                     (setq count (1+ count))
                   )
                 )
                )
                ((or (= loadType "FACE_PRESSURE") (= loadType "FACE_TOTAL_FORCE"))
                 (setq info (get-shell-center-normal ent)
                       cenPt (car info) diagLen (caddr info)
                       loadTypeTag (if (= loadType "FACE_TOTAL_FORCE") "TOTAL" "PRESSURE"))
                 (if (and cenPt (or unitVec normalP))
                   (progn
                     (setq visBlk (create-shell-faceload-block cenPt diagLen loadTypeTag mag unitVec unitStr))
                     (setq visHandle (cdr (assoc 5 (entget visBlk))))
                     (setq dirCode (if normalP (cons 1000 "NORMAL") (cons 1013 unitVec)))
                     (entmod (append (entget visBlk)
                                     (list (list -3 (list "MY_CAE_SHELL_LOAD" (cons 1005 entHandle))))))
                     (setq newRecs (append newRecs
                       (list (cons 1000 loadType) (cons 1000 lc) (cons 1040 mag)
                             (cons 1000 unitStr) dirCode
                             (cons 1005 visHandle) (cons 1070 0))))
                     (setq count (1+ count))
                   )
                 )
                )
              )
              (setq idx (+ idx headLen numPts))
            )
            (if newRecs
              (progn
                (entmod (append (entget ent) (list (list -3 (cons "MY_CAE_SHELL_LOAD" newRecs)))))
                (entupd ent)
              )
            )
          )
        )
        (setq i (1+ i))
      )
    )
  )
  count
)

(defun refresh-shell-bcs (/ ss i ent entHandle entData xdata appData idx newRecs
                           scopeTag uMask rMask uVecs rVecs numPts pts j
                           visBlk visHandle count info)
  (vl-load-com)
  (setq count 0
        ss (ssget "_X" (list (cons 0 (cae-shell-type-filter))
                             '(-3 ("MY_CAE_SHELL_BC")))))
  (if ss
    (progn
      (setq i 0)
      (while (< i (sslength ss))
        (setq ent (ssname ss i)
              entData (entget ent '("MY_CAE_SHELL_BC"))
              entHandle (cdr (assoc 5 entData))
              xdata (assoc -3 entData))
        (if xdata
          (progn
            (setq appData (cdr (cadr xdata)) newRecs nil idx 0)
            (while (< idx (length appData))
              (setq scopeTag (cdr (nth idx appData))
                    uMask (cdr (nth (+ idx 1) appData))
                    rMask (cdr (nth (+ idx 5) appData))
                    numPts (cdr (nth (+ idx 10) appData))
                    uVecs nil rVecs nil)
              (if (>= (atoi (substr uMask 1 1)) 1)
                (setq uVecs (append uVecs (list (cdr (nth (+ idx 2) appData)))))
              )
              (if (>= (atoi (substr uMask 2 1)) 1)
                (setq uVecs (append uVecs (list (cdr (nth (+ idx 3) appData)))))
              )
              (if (>= (atoi (substr uMask 3 1)) 1)
                (setq uVecs (append uVecs (list (cdr (nth (+ idx 4) appData)))))
              )
              (if (>= (atoi (substr rMask 1 1)) 1)
                (setq rVecs (append rVecs (list (cdr (nth (+ idx 6) appData)))))
              )
              (if (>= (atoi (substr rMask 2 1)) 1)
                (setq rVecs (append rVecs (list (cdr (nth (+ idx 7) appData)))))
              )
              (if (>= (atoi (substr rMask 3 1)) 1)
                (setq rVecs (append rVecs (list (cdr (nth (+ idx 8) appData)))))
              )
              (setq pts nil j 0)
              (while (< j numPts)
                (setq pts (append pts (list (cdr (nth (+ idx 11 j) appData)))))
                (setq j (1+ j))
              )
              (if (= scopeTag "FACE_BC")
                (progn
                  (setq info (get-shell-center-normal ent))
                  (setq pts (list (car info)))
                )
              )
              (if pts
                (progn
                  (setq visBlk (create-shell-bc-block pts scopeTag uVecs rVecs uMask rMask))
                  (setq visHandle (cdr (assoc 5 (entget visBlk))))
                  (entmod (append (entget visBlk)
                                  (list (list -3 (list "MY_CAE_SHELL_BC" (cons 1005 entHandle))))))
                  (setq newRecs (append newRecs
                    (list (cons 1000 scopeTag)
                          (cons 1000 uMask)
                          (nth (+ idx 2) appData) (nth (+ idx 3) appData) (nth (+ idx 4) appData)
                          (cons 1000 rMask)
                          (nth (+ idx 6) appData) (nth (+ idx 7) appData) (nth (+ idx 8) appData)
                          (cons 1005 visHandle)
                          (cons 1070 (if (= scopeTag "EDGE_BC") (length pts) 0)))
                    (if (= scopeTag "EDGE_BC")
                      (mapcar '(lambda (p) (cons 1010 p)) pts)
                      nil)))
                  (setq count (1+ count))
                )
              )
              (setq idx (+ idx 11 numPts))
            )
            (if newRecs
              (progn
                (entmod (append (entget ent) (list (list -3 (cons "MY_CAE_SHELL_BC" newRecs)))))
                (entupd ent)
              )
            )
          )
        )
        (setq i (1+ i))
      )
    )
  )
  count
)

(defun refresh-shell-props (/ ss i ent entHandle entData xdata appData
                             theoryType thick offZ matName info cenPt normVec diagLen
                             visBlk visHandle count)
  (vl-load-com)
  (setq count 0
        ss (ssget "_X" (list (cons 0 (cae-shell-type-filter))
                             '(-3 ("MY_CAE_SHELL_PROP")))))
  (if ss
    (progn
      (setq i 0)
      (cae-vis-begin-batch)
      (while (< i (sslength ss))
        (setq ent (ssname ss i)
              entData (entget ent '("MY_CAE_SHELL_PROP"))
              entHandle (cdr (assoc 5 entData))
              xdata (assoc -3 entData))
        (if xdata
          (if (not (cae-shell-plate-p ent))
            (cae-clear-shell-prop ent)
            (progn
            (setq appData (cdr (cadr xdata)))
            (setq theoryType (cdr (nth 0 appData))
                  thick (cdr (nth 1 appData))
                  offZ (cdr (nth 2 appData))
                  matName (cdr (nth 3 appData)))
            (setq info (get-shell-center-normal ent)
                  cenPt (car info) normVec (cadr info) diagLen (caddr info))
            (setq visBlk (create-shell-prop-block cenPt normVec diagLen theoryType thick offZ matName))
            (setq visHandle (cdr (assoc 5 (entget visBlk))))
            (entmod (append (entget ent)
                            (list (list -3 (list "MY_CAE_SHELL_PROP"
                              (cons 1000 theoryType) (cons 1040 thick)
                              (cons 1040 offZ) (cons 1000 matName)
                              (cons 1005 visHandle))))))
            (entupd ent)
            (entmod (append (entget visBlk)
                            (list (list -3 (list "MY_CAE_SHELL_PROP" (cons 1005 entHandle))))))
            (setq count (1+ count))
            )
          )
        )
        (setq i (1+ i))
      )
      (cae-vis-end-batch)
    )
  )
  count
)

(defun refresh-springs (/ ss i ent entData beamHandle p1 p2 beamLen xdata appData j
                          endTag kindTag k1 k2 k3 unitStr ptNode visBlkEnt visHandle
                          newRecords count)
  (setq count 0 ss (ssget "_X" '((0 . "LINE") (-3 ("MY_CAE_SPRING")))))
  (if ss
    (progn
      (setq i 0)
      (while (< i (sslength ss))
        (setq ent (ssname ss i) entData (entget ent '("MY_CAE_SPRING")))
        (setq beamHandle (cdr (assoc 5 entData)))
        (setq p1 (cdr (assoc 10 entData)) p2 (cdr (assoc 11 entData))
              beamLen (distance p1 p2))
        (setq xdata (assoc -3 entData))
        (if xdata
          (progn
            (setq appData (cdr (cadr xdata)) newRecords nil j 0)
            (while (< j (length appData))
              (setq endTag (cdr (nth j appData))
                    kindTag (cdr (nth (+ j 1) appData))
                    k1 (cdr (nth (+ j 2) appData))
                    k2 (cdr (nth (+ j 3) appData))
                    k3 (cdr (nth (+ j 4) appData))
                    unitStr (cdr (nth (+ j 5) appData))
                    ptNode (if (= endTag "START") p1 p2))
              (cond
                ((= kindTag "TRANS")
                 (if (or (not unitStr) (/= (type unitStr) 'STR) (= unitStr "N/mm") (= unitStr "Nmm"))
                   (setq unitStr "N-mm")
                 )
                 (if (= unitStr "kN/m") (setq unitStr "kN-m"))
                 (setq visBlkEnt (create-trans-spring-block ptNode beamLen k1 k2 k3 unitStr endTag))
                )
                ((= kindTag "ROT")
                 (if (or (not unitStr) (/= (type unitStr) 'STR) (= unitStr "N.mm/rad"))
                   (setq unitStr "Nmm/rad")
                 )
                 (if (= unitStr "N.m/rad") (setq unitStr "Nm/rad"))
                 (setq visBlkEnt (create-rot-spring-block ptNode beamLen k1 k2 k3 unitStr endTag))
                )
                (T (setq visBlkEnt nil))
              )
              (if visBlkEnt
                (progn
                  (setq visHandle (cdr (assoc 5 (entget visBlkEnt))))
                  (entmod (append (entget visBlkEnt)
                                  (list (list -3 (list "MY_CAE_SPRING"
                                    (cons 1005 beamHandle) (cons 1000 endTag) (cons 1000 kindTag))))))
                  (setq newRecords (append newRecords (list
                    (cons 1000 endTag) (cons 1000 kindTag)
                    (cons 1040 k1) (cons 1040 k2) (cons 1040 k3)
                    (cons 1000 unitStr) (cons 1005 visHandle))))
                  (setq count (1+ count))
                )
              )
              (setq j (+ j 7))
            )
            (if newRecords
              (progn
                (entmod (append (entget ent) (list (list -3 (cons "MY_CAE_SPRING" newRecords)))))
                (entupd ent)
              )
            )
          )
        )
        (setq i (1+ i))
      )
    )
  )
  count
)

(defun c:REFRESH_ALL (/ ssOld i cDist cPt cMom cBc cComp cSec cSpring cShLoad cShBc cShProp cSpot cSeam)
  (vl-load-com)
  (unlock-vis-layer)
  (setq ssOld (ssget "_X" '((8 . "CAE_VIS_LOAD,CAE_VIS_BC,CAE_VIS_SEC,CAE_VIS_WELD,CAE_LOAD_VIS"))))
  (if ssOld
    (progn
      (setq i 0)
      (while (< i (sslength ssOld))
        (entdel (ssname ssOld i))
        (setq i (1+ i))
      )
    )
  )
  (setq cDist   (refresh-dist-loads)
        cPt     (refresh-point-loads)
        cMom    (refresh-moment-loads)
        cBc     (refresh-simple-bcs)
        cComp   (refresh-comp-bcs)
        cSpring (refresh-springs)
        cSec    (refresh-sections)
        cShLoad (refresh-shell-loads)
        cShBc   (refresh-shell-bcs)
        cShProp (refresh-shell-props)
        cSpot   (refresh-spot-welds)
        cSeam   (refresh-seam-welds))
  (lock-vis-layer)
  (princ (strcat (_T "\n[刷新] 梁截面=" "\n[Refresh] BeamSec=") (itoa cSec)
                 (_T " 分布=" " Dist=") (itoa cDist)
                 (_T " 集中=" " Point=") (itoa cPt)
                 (_T " 弯矩=" " Moment=") (itoa cMom)
                 (_T " 约束=" " BC=") (itoa cBc)
                 (_T " 复合=" " Comp=") (itoa cComp)
                 (_T " 弹簧=" " Spring=") (itoa cSpring)))
  (princ (strcat (_T "\n       板壳属性=" "\n       ShellProp=") (itoa cShProp)
                 (_T " 板壳载荷=" " ShellLoad=") (itoa cShLoad)
                 (_T " 板壳约束=" " ShellBC=") (itoa cShBc)
                 (_T " 点焊=" " Spot=") (itoa cSpot)
                 (_T " 满焊=" " Seam=") (itoa cSeam)))
  (princ)
)

(defun c:SETSCALE (/ sLoad sBc sSec)
  (princ (strcat (_T "\n当前比例 载荷(梁+板壳):" "\nCurrent scale Load(beam+shell):") (rtos *CAE_SCALE_LOAD* 2 2)
                 (_T " 约束:" " BC:") (rtos *CAE_SCALE_BC* 2 2)
                 (_T " 截面/属性:" " Sec/Prop:") (rtos *CAE_SCALE_SEC* 2 2)))
  (setq sLoad (getreal (strcat (_T "\n【载荷】比例 <" "\n[Load] scale <") (rtos *CAE_SCALE_LOAD* 2 2) ">: ")))
  (if (and sLoad (> sLoad 0.0)) (setq *CAE_SCALE_LOAD* sLoad))
  (setq sBc (getreal (strcat (_T "\n【约束】比例 <" "\n[BC] scale <") (rtos *CAE_SCALE_BC* 2 2) ">: ")))
  (if (and sBc (> sBc 0.0)) (setq *CAE_SCALE_BC* sBc))
  (setq sSec (getreal (strcat (_T "\n【截面/板壳属性】比例 <" "\n[Section/ShellProp] scale <") (rtos *CAE_SCALE_SEC* 2 2) ">: ")))
  (if (and sSec (> sSec 0.0)) (setq *CAE_SCALE_SEC* sSec))
  (princ (_T "\n正在按新比例重绘梁+板壳..." "\nRedrawing beam+shell with new scales..."))
  (c:REFRESH_ALL)
)

;;; ---------- 图层显隐（梁与板壳共用 CAE_VIS_*；静默取反 62）----------
(defun toggle-cae-layer (layName cnLabel / en ed colVal)
  (setq en (tblobjname "LAYER" layName))
  (if en
    (progn
      (setq ed (entget en) colVal (cdr (assoc 62 ed)))
      (entmod (subst (cons 62 (- colVal)) (assoc 62 ed) ed))
      (if (< colVal 0)
        (princ (strcat (_T "\n[显示] " "\n[ON] ") cnLabel))
        (princ (strcat (_T "\n[隐藏] " "\n[OFF] ") cnLabel))
      )
    )
    (princ (strcat (_T "\n[提示] 图层 " "\n[Hint] Layer ") layName (_T " 尚未创建。" " not created yet.")))
  )
  (princ)
)
(defun c:TOGGLESEC () (toggle-cae-layer "CAE_VIS_SEC" (_T "截面/板壳属性" "Section/ShellProp")))
(defun c:TOGGLELOAD () (toggle-cae-layer "CAE_VIS_LOAD" (_T "载荷(梁+板壳)" "Load (beam+shell)")))
(defun c:TOGGLEBC () (toggle-cae-layer "CAE_VIS_BC" (_T "约束(梁+板壳)" "BC (beam+shell)")))
(defun c:TOGGLEWELD () (toggle-cae-layer "CAE_VIS_WELD" (_T "焊缝/焊点" "Welds")))

;;; ====================================================================
;;; 板壳：几何 / 边面载荷 / 属性 / 复合约束
;;; ====================================================================

;;; 从克隆炸开结果中收集边端点；EXTRUDEDSURFACE 常先变 REGION，再二次炸开
(defun cae-collect-explode-edge-pts (markEnt / ssTmp subEnt eType pts obj nrm again e2 mark2)
  (setq ssTmp (ssadd) pts nil nrm nil again nil)
  (setq subEnt (entnext markEnt))
  (while subEnt
    (ssadd subEnt ssTmp)
    (setq eType (cdr (assoc 0 (entget subEnt))))
    (cond
      ((member eType '("LINE" "ARC" "CIRCLE" "SPLINE" "ELLIPSE" "LWPOLYLINE"))
       (if (not (vl-catch-all-error-p
                  (vl-catch-all-apply 'vlax-curve-getStartPoint (list subEnt))))
         (setq pts (append pts
                           (list (vlax-curve-getStartPoint subEnt)
                                 (vlax-curve-getEndPoint subEnt))))
       )
      )
      ((= eType "REGION")
       (setq obj (vlax-ename->vla-object subEnt))
       (if (and (not nrm) (vlax-property-available-p obj 'Normal))
         (setq nrm (vec-unit (vlax-safearray->list
                               (vlax-variant-value (vla-get-Normal obj)))))
       )
       (setq again (cons subEnt again))
      )
      ((cae-modern-surface-p eType)
       (setq again (cons subEnt again))
      )
    )
    (setq subEnt (entnext subEnt))
  )
  ;; 二次炸开：REGION / 曲面 → 边线（e2 炸后从库中消失，新边并入 ssTmp）
  (foreach e2 again
    (if (and e2 (entget e2))
      (progn
        (setq mark2 (entlast))
        (command "_.EXPLODE" e2)
        (setq subEnt (entnext mark2))
        (while subEnt
          (ssadd subEnt ssTmp)
          (setq eType (cdr (assoc 0 (entget subEnt))))
          (if (member eType '("LINE" "ARC" "CIRCLE" "SPLINE" "ELLIPSE" "LWPOLYLINE"))
            (if (not (vl-catch-all-error-p
                        (vl-catch-all-apply 'vlax-curve-getStartPoint (list subEnt))))
              (setq pts (append pts
                                (list (vlax-curve-getStartPoint subEnt)
                                      (vlax-curve-getEndPoint subEnt))))
            )
          )
          (if (and (= eType "REGION") (not nrm))
            (progn
              (setq obj (vlax-ename->vla-object subEnt))
              (if (vlax-property-available-p obj 'Normal)
                (setq nrm (vec-unit (vlax-safearray->list
                                      (vlax-variant-value (vla-get-Normal obj)))))
              )
            )
          )
          (setq subEnt (entnext subEnt))
        )
      )
    )
  )
  (list ssTmp pts nrm)
)

(defun get-shell-center-normal (ent / ed eType obj normWCS minPt maxPt cenPt diagLen verts v1 v2 i beforeEnt tempClone pack ssTmp pts)
  (vl-load-com)
  (setq ed (entget ent))
  (setq eType (cdr (assoc 0 ed)))
  (setq obj (vlax-ename->vla-object ent))
  
  ;; 1. 计算包围盒中心与特征对角线长度
  (vla-getBoundingBox obj 'minPt 'maxPt)
  (setq minPt (vlax-safearray->list minPt))
  (setq maxPt (vlax-safearray->list maxPt))
  (setq cenPt (vec-scale (vec-add minPt maxPt) 0.5))
  (setq diagLen (distance minPt maxPt))
  (setq normWCS nil)
  
  ;; 2. 按实体类型精确提取真实三维法向量
  (cond
    ;; A：REGION / PLANESURFACE / 部分曲面 — ActiveX Normal
    ((and (or (= eType "REGION") (= eType "PLANESURFACE") (cae-modern-surface-p eType))
          (vlax-property-available-p obj 'Normal))
     (setq normWCS (vec-unit (vlax-safearray->list (vlax-variant-value (vla-get-Normal obj)))))
    )
    ;; B：LWPOLYLINE / CIRCLE / ARC 自带组码 210
    ((assoc 210 ed)
     (setq normWCS (vec-unit (cdr (assoc 210 ed))))
    )
    ;; C：MESH -> 组码 10 顶点叉乘
    ((= eType "MESH")
     (setq verts nil)
     (foreach item ed
       (if (= (car item) 10) (setq verts (append verts (list (cdr item)))))
     )
     (if (>= (length verts) 3)
       (progn
         (setq v1 (vec-sub (nth 1 verts) (nth 0 verts)))
         (setq i 2)
         (while (and (< i (length verts)) (not normWCS))
           (setq v2 (vec-sub (nth i verts) (nth 0 verts)))
           (setq normWCS (vec-unit (vec-cross v1 v2)))
           (setq i (1+ i))
         )
       )
     )
    )
    ;; D：3DFACE -> 组码 10, 11, 12 叉乘
    ((= eType "3DFACE")
     (setq v1 (vec-sub (cdr (assoc 11 ed)) (cdr (assoc 10 ed))))
     (setq v2 (vec-sub (cdr (assoc 12 ed)) (cdr (assoc 10 ed))))
     (setq normWCS (vec-unit (vec-cross v1 v2)))
    )
  )
  
  ;; 兜底：克隆炸开（EXTRUDEDSURFACE 常需二次炸开 REGION→边）
  (if (not normWCS)
    (progn
      (setq beforeEnt (entlast))
      (command "_.COPY" ent "" '(0.0 0.0 0.0) '(0.0 0.0 0.0))
      (setq tempClone (entlast))
      (if (not (equal beforeEnt tempClone))
        (progn
          (command "_.EXPLODE" tempClone)
          (setq pack (cae-collect-explode-edge-pts beforeEnt))
          (setq ssTmp (car pack) pts (cadr pack) normWCS (caddr pack))
          (if (and (not normWCS) (>= (length pts) 3))
            (progn
              (setq v1 (vec-sub (nth 1 pts) (nth 0 pts)))
              (setq i 2)
              (while (and (< i (length pts)) (not normWCS))
                (setq v2 (vec-sub (nth i pts) (nth 0 pts)))
                (setq normWCS (vec-unit (vec-cross v1 v2)))
                (setq i (1+ i))
              )
            )
          )
          (if (and ssTmp (> (sslength ssTmp) 0)) (command "_.ERASE" ssTmp ""))
        )
      )
    )
  )
  
  (if (not normWCS) (setq normWCS '(0.0 0.0 1.0)))
  (list cenPt normWCS diagLen)
)


;;; 空间三点定圆弧离散 (p1, pMid, p2 -> numSeg+1 个三维点)
(defun sample-3pt-arc-3d (p1 pMid p2 numSeg / v1 v2 n ex ey x2 x3 y3 d ux uy center3d rad a1 am a2 da step i ang pts)
  (setq v1 (vec-sub pMid p1))
  (setq v2 (vec-sub p2 p1))
  (setq n (vec-unit (vec-cross v1 v2)))
  (if (not n)
    (list p1 p2)
    (progn
      (setq ex (vec-unit v2))
      (setq ey (vec-cross n ex))
      (setq x2 (distance p1 p2))
      (setq x3 (+ (* (car v1) (car ex)) (* (cadr v1) (cadr ex)) (* (caddr v1) (caddr ex))))
      (setq y3 (+ (* (car v1) (car ey)) (* (cadr v1) (cadr ey)) (* (caddr v1) (caddr ey))))
      
      (setq d (* 2.0 (- (* x2 y3))))
      (setq ux (/ (- (* y3 (* x2 x2))) d))
      (setq uy (/ (- (* x2 (+ (* x3 x3) (* y3 y3))) (* x3 (* x2 x2))) d))
      (setq rad (sqrt (+ (* ux ux) (* uy uy))))
      (setq center3d (vec-add p1 (vec-add (vec-scale ex ux) (vec-scale ey uy))))
      
      (setq a1 (atan (- 0.0 uy) (- 0.0 ux)))
      (setq am (atan (- y3 uy) (- x3 ux)))
      (setq a2 (atan (- 0.0 uy) (- x2 ux)))
      
      (setq da (- a2 a1))
      (if (> da pi) (setq da (- da (* 2.0 pi))))
      (if (< da (- pi)) (setq da (+ da (* 2.0 pi))))
      (if (not (or (and (< a1 am) (< am (+ a1 da))) (and (> a1 am) (> am (+ a1 da)))))
        (setq da (if (> da 0.0) (- da (* 2.0 pi)) (+ da (* 2.0 pi))))
      )
      
      (setq step (/ da (float numSeg)) pts nil i 0)
      (while (<= i numSeg)
        (setq ang (+ a1 (* i step)))
        (setq pts (append pts (list (vec-add center3d
                                             (vec-add (vec-scale ex (* rad (cos ang)))
                                                      (vec-scale ey (* rad (sin ang))))))))
        (setq i (1+ i))
      )
      pts
    )
  )
)

;;; 创建【不可分割的整体】板壳边界线载荷块 (*U) -> 放入 CAE_VIS_LOAD
;;; 与 K/KR/BC 相同：沿载荷方向缩回一圆半径，尖端落在圆周
(defun create-shell-edgeload-block (ptsList loadMag unitVec unitStr / pOrigin totalLen i tipR arrowLen
                                           locPts pEndRel ptOnEdge tip ptTail prevTail
                                           labelPt labelStr blkDefName blkRef)
  (unlock-vis-layer)
  (setq pOrigin (car ptsList))
  (setq totalLen 0.0 i 0)
  (while (< i (1- (length ptsList)))
    (setq totalLen (+ totalLen (distance (nth i ptsList) (nth (1+ i) ptsList))))
    (setq i (1+ i))
  )
  (setq arrowLen (* (max (* totalLen 0.14) 80.0) *CAE_SCALE_LOAD*))
  (setq tipR (* arrowLen 0.08))
  (entmake (list '(0 . "BLOCK") '(2 . "*U") '(70 . 1) '(10 0.0 0.0 0.0)))
  (if (= (length ptsList) 2)
    (progn
      (setq pEndRel (vec-sub (cadr ptsList) pOrigin))
      (setq locPts nil i 0)
      (while (<= i 4)
        (setq locPts (append locPts (list (vec-scale pEndRel (/ (float i) 4.0)))))
        (setq i (1+ i))
      )
    )
    (setq locPts (mapcar '(lambda (p) (vec-sub p pOrigin)) ptsList))
  )
  (setq prevTail nil)
  (foreach ptOnEdge locPts
    (setq tip (vec-sub ptOnEdge (vec-scale unitVec tipR)))
    (setq ptTail (vec-sub ptOnEdge (vec-scale unitVec arrowLen)))
    (entmake (list '(0 . "CIRCLE") '(8 . "0") '(62 . 1) (cons 10 ptOnEdge) (cons 40 tipR)))
    (entmake (list '(0 . "LINE") '(8 . "0") '(62 . 1) (cons 10 ptTail) (cons 11 tip)))
    (if prevTail
      (entmake (list '(0 . "LINE") '(8 . "0") '(62 . 1) (cons 10 prevTail) (cons 11 ptTail)))
    )
    (setq prevTail ptTail)
  )
  (setq labelPt (vec-sub (nth (/ (length locPts) 2) locPts) (vec-scale unitVec (* arrowLen 1.25))))
  (setq unitStr (normalize-dist-unit unitStr))
  (setq labelStr (strcat "q_edge=" (rtos loadMag 2 1) " " unitStr " (" (rtos (car unitVec) 2 2) "," (rtos (cadr unitVec) 2 2) "," (rtos (caddr unitVec) 2 2) ")"))
  (entmake (list '(0 . "TEXT") '(8 . "0") '(62 . 1) (cons 10 labelPt) (cons 40 (* arrowLen 0.24)) (cons 1 labelStr)))
  (setq blkDefName (entmake '((0 . "ENDBLK"))))
  (setq blkRef (entmakex (list '(0 . "INSERT") '(8 . "CAE_VIS_LOAD") (cons 2 blkDefName) (cons 10 pOrigin))))
  (lock-vis-layer)
  blkRef
)

;;; 升级版：在板壳几何中心绘制【单个立体双翼大箭头】整体块（彻底杜绝小面片超界问题）
(defun create-shell-faceload-block (cenPt diagLen loadTypeTag valMag unitVec unitStr / arrowLen ptTail ptConeBase perp1 perp2 pWing1 pWing2 labelPt labelStr blkDefName blkRef)
  (unlock-vis-layer)
  ;; 自适应箭头长度，并受全局比例 *CAE_SCALE_LOAD* 控制
  (setq arrowLen (* (max (* diagLen 0.16) 80.0) *CAE_SCALE_LOAD*))
  
  (entmake (list '(0 . "BLOCK") '(2 . "*U") '(70 . 1) '(10 0.0 0.0 0.0)))
  (entmake (list '(0 . "CIRCLE") '(8 . "0") '(62 . 30) '(10 0.0 0.0 0.0) (cons 40 (* arrowLen 0.08))))
  (if (or (not unitStr) (= unitStr ""))
    (setq unitStr (if (= loadTypeTag "TOTAL") "N" "MPa"))
  )
  (if unitVec
    (progn
      ;; 全局向量：一支指向面心的箭头
      (setq ptTail (vec-sub '(0.0 0.0 0.0) (vec-scale unitVec arrowLen)))
      (entmake (list '(0 . "LINE") '(8 . "0") '(62 . 30) (cons 10 ptTail) '(11 0.0 0.0 0.0)))
      (setq ptConeBase (vec-sub '(0.0 0.0 0.0) (vec-scale unitVec (* arrowLen 0.25))))
      (setq perp1 (cadr (make-local-basis unitVec)))
      (setq perp2 (vec-unit (vec-cross unitVec perp1)))
      (foreach p (list perp1 perp2)
        (setq pWing1 (vec-add ptConeBase (vec-scale p (* arrowLen 0.10))))
        (setq pWing2 (vec-sub ptConeBase (vec-scale p (* arrowLen 0.10))))
        (entmake (list '(0 . "LINE") '(8 . "0") '(62 . 30) (cons 10 pWing1) '(11 0.0 0.0 0.0)))
        (entmake (list '(0 . "LINE") '(8 . "0") '(62 . 30) (cons 10 pWing2) '(11 0.0 0.0 0.0)))
      )
      (setq labelPt (vec-sub '(0.0 0.0 0.0) (vec-scale unitVec (* arrowLen 1.15))))
      (setq labelStr (if (= loadTypeTag "TOTAL")
                       (strcat "F_total=" (rtos valMag 2 2) " " unitStr " (" (rtos (car unitVec) 2 2) "," (rtos (cadr unitVec) 2 2) "," (rtos (caddr unitVec) 2 2) ")")
                       (strcat "P_face=" (rtos valMag 2 3) " " unitStr " (" (rtos (car unitVec) 2 2) "," (rtos (cadr unitVec) 2 2) "," (rtos (caddr unitVec) 2 2) ")")))
    )
    (progn
      ;; 法向：不记录固定方向，只标数值
      (setq labelPt (list 0.0 0.0 (* arrowLen 0.35)))
      (setq labelStr (if (= loadTypeTag "TOTAL")
                       (strcat "F_total=" (rtos valMag 2 2) " " unitStr " normal")
                       (strcat "P_face=" (rtos valMag 2 3) " " unitStr " normal")))
    )
  )
  (entmake (list '(0 . "TEXT") '(8 . "0") '(62 . 30) (cons 10 labelPt) (cons 40 (* arrowLen 0.22)) (cons 1 labelStr)))
  
  (setq blkDefName (entmake '((0 . "ENDBLK"))))
  (setq blkRef (entmakex (list '(0 . "INSERT") '(8 . "CAE_VIS_LOAD") (cons 2 blkDefName) (cons 10 cenPt))))
  (lock-vis-layer)
  blkRef
)


;;; ====================================================================
;;; 三维板壳加载模块（第二部分：规范化关键字交互命令 SETSHELLLOAD / DELSHELLLOAD）
;;; ====================================================================

(defun c:SETSHELLLOAD (/ selMain mainEnt mainType mainHandle loadScope edgeSS selEdge edgeEnt pts loadMag unitStr vecInput unitVec shellInfo cenPt normVec diagLen pressType subType valMode loadTypeTag visBlk visHandle oldXd newRecs ptPairs)
  (vl-load-com)
  (register-shell-load-app)
  
  (setq selMain (entsel (_T "\n[第1步] 请选择目标板壳面片 (MESH / REGION / SURFACE / EXTRUDEDSURFACE / …): "
                             "\n[Step 1] Select shell face (MESH / REGION / SURFACE / EXTRUDEDSURFACE / …): ")))
  (if selMain
    (progn
      (setq mainEnt (car selMain))
      (setq mainType (cdr (assoc 0 (entget mainEnt))))
      (setq mainHandle (cdr (assoc 5 (entget mainEnt))))
      
      (if (cae-shell-type-p mainType)
        (progn
          (initget "Edge Face")
          (setq loadScope (getkword (_T "\n加载位置 Edge=边线载荷, Face=面压强/面力 [Edge/Face] <Face>: "
                                 "\nLocation Edge=edge load, Face=face pressure/force [Edge/Face] <Face>: ")))
          (if (not loadScope) (setq loadScope "Face"))
          
          (cond
            ;; 分支 A：先抽出边界，再选一条施加分布线载荷
            ((= loadScope "Edge")
             (princ (_T "\n正在提取边界…" "\nExtracting boundaries…"))
             (setq edgeSS (cae-materialize-face-edges mainEnt))
             (if (not edgeSS)
               (princ (_T "\n[错误] 未能从该面提取出边界。" "\n[Error] No boundary curves from this face."))
               (progn
                 (cae-ent-invisible mainEnt T)
                 (princ (strcat (_T "\n已显示 " "\nShowing ") (itoa (sslength edgeSS))
                                (_T " 条红色边界。" " red boundary curve(s).")))
                 (setq selEdge (entsel (_T "\n[第2步] 选择要加载的红色边界: "
                                            "\n[Step 2] Select the red boundary to load: ")))
                 (cae-ent-invisible mainEnt nil)
                 (if (and selEdge (ssmemb (car selEdge) edgeSS))
                   (progn
                     (setq edgeEnt (car selEdge))
                     (setq pts (cae-sample-boundary-curve edgeEnt))
                     (if (not pts)
                       (princ (_T "\n[错误] 未能读取这条边界曲线。"
                                  "\n[Error] Could not sample that boundary curve."))
                     )
                   )
                   (if selEdge
                     (princ (_T "\n[错误] 请选择刚显示的红色边界。"
                                "\n[Error] Pick one of the red boundary curves."))
                   )
                 )
                 (cae-erase-ss edgeSS)
               )
             )

             (if pts
               (progn
                 (setq loadMag (getreal (_T "\n边界分布线载荷集度数值 <10.0>: "
                                           "\nEdge line-load magnitude <10.0>: ")))
                 (if (not loadMag) (setq loadMag 10.0))
                 (setq unitStr (ask-dist-unit))
                 
                 (setq vecInput (getpoint (_T "\n全局载荷方向向量 X,Y,Z <0,0,-1>: "
                                              "\nGlobal load direction X,Y,Z <0,0,-1>: ")))
                 (if (not vecInput)
                   (setq unitVec '(0.0 0.0 -1.0))
                   (setq unitVec (vec-unit (trans vecInput 1 0 T)))
                 )
                 
                 (if unitVec
                   (progn
                     (setq visBlk (create-shell-edgeload-block pts loadMag unitVec unitStr))
                     (setq visHandle (cdr (assoc 5 (entget visBlk))))
                     
                     (setq ptPairs (mapcar '(lambda (p) (cons 1010 p)) pts))
                     (setq oldXd (cdr (cadr (assoc -3 (entget mainEnt '("MY_CAE_SHELL_LOAD"))))))
                     (setq newRecs (append oldXd
                       (list (cons 1000 "EDGE_LOAD")
                             (cons 1000 "LC1")
                             (cons 1040 loadMag)
                             (cons 1000 unitStr)
                             (cons 1013 unitVec)
                             (cons 1005 visHandle)
                             (cons 1070 (length pts)))
                       ptPairs))
                     
                     (entmod (append (entget mainEnt) (list (list -3 (cons "MY_CAE_SHELL_LOAD" newRecs)))))
                     (entupd mainEnt)
                     (entmod (append (entget visBlk) (list (list -3 (list "MY_CAE_SHELL_LOAD" (cons 1005 mainHandle))))))
                     (princ (strcat (_T "\n[成功] 已为板壳边界施加线分布载荷: " "\n[OK] Edge line load: ") (rtos loadMag 2 2) " " unitStr))
                   )
                 )
               )
             )
            )
            
            ;; 分支 B：在整个板壳面上施加面载荷（支持【面压强】与【面总载荷】两种模式）
            ((= loadScope "Face")
             (setq shellInfo (get-shell-center-normal mainEnt))
             (setq cenPt (car shellInfo) normVec (cadr shellInfo) diagLen (caddr shellInfo))
             
             ;; 选择是按【面压强(分布面力)】还是【面总载荷(总合力)】输入
             (initget "Pressure Total")
             (setq valMode (getkword (_T "\n面载荷输入 Pressure=面压强, Total=面总合力 [Pressure/Total] <Pressure>: "
                               "\nFace load input Pressure/Total [Pressure/Total] <Pressure>: ")))
             (if (not valMode) (setq valMode "Pressure"))
             
             (if (= valMode "Pressure")
               (progn
                 (setq loadMag (getreal (_T "\n分布面压强数值（可负） <1.0>: "
                                           "\nFace pressure magnitude (signed) <1.0>: ")))
                 (if (not loadMag) (setq loadMag 1.0))
                 (setq unitStr (ask-pressure-unit))
                 (setq loadTypeTag "PRESSURE")
               )
               (progn
                 (setq loadMag (getreal (_T "\n面总合力数值（可负） <50.0>: "
                                           "\nTotal face force magnitude (signed) <50.0>: ")))
                 (if (not loadMag) (setq loadMag 50.0))
                 (setq unitStr (ask-force-unit))
                 (setq loadTypeTag "TOTAL")
               )
             )
             
             ;; 选择加载方向（法向或全局向量）
             (initget "Normal Vector")
             (setq pressType (getkword (_T "\n面载荷方向 Normal=板面法向, Vector=全局向量 [Normal/Vector] <Normal>: "
                                 "\nFace load direction Normal/Vector [Normal/Vector] <Normal>: ")))
             (if (not pressType) (setq pressType "Normal"))
             
             (if (= pressType "Normal")
               ;; 曲面各处法向不同，这里不计算固定方向
               (setq unitVec nil)
               (progn
                 (setq vecInput (getpoint (_T "\n全局面力方向向量 X,Y,Z <0,0,-1>: "
                                      "\nGlobal face-load direction X,Y,Z <0,0,-1>: ")))
                 (if (not vecInput)
                   (setq unitVec '(0.0 0.0 -1.0))
                   (setq unitVec (vec-unit (trans vecInput 1 0 T)))
                 )
               )
             )
             
             ;; 组合标准子类型标识: "FACE_PRESSURE" 或 "FACE_TOTAL_FORCE"
             (setq subType (if (= loadTypeTag "TOTAL") "FACE_TOTAL_FORCE" "FACE_PRESSURE"))
             
             (if (and cenPt (or unitVec (= pressType "Normal")))
               (progn
                 (setq visBlk (create-shell-faceload-block cenPt diagLen loadTypeTag loadMag unitVec unitStr))
                 (setq visHandle (cdr (assoc 5 (entget visBlk))))
                 
                 (setq oldXd (cdr (cadr (assoc -3 (entget mainEnt '("MY_CAE_SHELL_LOAD"))))))
                 (setq newRecs (append oldXd
                   (list (cons 1000 subType)
                         (cons 1000 "LC1")
                         (cons 1040 loadMag)
                         (cons 1000 unitStr)
                         (if (= pressType "Normal")
                           (cons 1000 "NORMAL")
                           (cons 1013 unitVec))
                         (cons 1005 visHandle)
                         (cons 1070 0))))
                 
                 (entmod (append (entget mainEnt) (list (list -3 (cons "MY_CAE_SHELL_LOAD" newRecs)))))
                 (entupd mainEnt)
                 (entmod (append (entget visBlk) (list (list -3 (list "MY_CAE_SHELL_LOAD" (cons 1005 mainHandle))))))
                 (princ (strcat (_T "\n[成功] 已在板壳中心施加 [" "\n[OK] Face load at center [") subType "] "
                                (rtos loadMag 2 3) " " unitStr))
               )
             )
             
                         )
          )
        )
        (princ (strcat (_T "\n[错误] 不支持的面片实体类型: " "\n[Error] Unsupported entity type: ") mainType))
      )
    )
  )
  (princ)
)

(defun c:DELSHELLLOAD (/ ss i ent entData entType xdata appData idx numPts visHandle oldBlk targetEnt)
  (unlock-vis-layer)
  (princ (_T "\n请选择要清除载荷的【板壳面片】或【板壳载荷箭头整体符号】: "
         "\nSelect shell face(s) or shell-load symbol(s) to clear: "))
  (setq ss (ssget (list (cons 0 (cae-shell-type-filter-ins)))))
  (if ss
    (progn
      (setq i 0)
      (while (< i (sslength ss))
        (setq ent (ssname ss i))
        (setq entData (entget ent '("MY_CAE_SHELL_LOAD")))
        (setq entType (cdr (assoc 0 entData)))
        (setq xdata (assoc -3 entData))
        (if xdata
          (progn
            (setq appData (cdr (cadr xdata)))
            (if (/= entType "INSERT")
              (progn
                (setq idx 0)
                (while (< idx (length appData))
                  (setq visHandle (cdr (nth (+ idx 5) appData)))
                  (setq numPts    (cdr (nth (+ idx 6) appData)))
                  (if (and visHandle (setq oldBlk (handent visHandle)))
                    (if (entget oldBlk) (entdel oldBlk))
                  )
                  (setq idx (+ idx 7 numPts))
                )
                (entmod (append (entget ent) (list (list -3 (list "MY_CAE_SHELL_LOAD")))))
                (entupd ent)
              )
              (progn
                (setq targetEnt (handent (cdr (nth 0 appData))))
                (if (and targetEnt (entget targetEnt))
                  (progn
                    (entmod (append (entget targetEnt) (list (list -3 (list "MY_CAE_SHELL_LOAD")))))
                    (entupd targetEnt)
                  )
                )
                (entdel ent)
              )
            )
          )
        )
        (setq i (1+ i))
      )
      (princ (_T "\n[清除完成] 所选板壳载荷与可视化箭头已同步销毁。"
         "\n[Done] Shell loads and symbols removed."))
    )
  )
  (lock-vis-layer)
  (princ)
)

;;; ====================================================================
;;; 板壳属性与约束模块：几何提取与属性符号块
;;; ====================================================================

;;; 约束边界：可直接点选的曲线
(defun cae-boundary-curve-p (eType)
  (member eType '("LINE" "ARC" "CIRCLE" "ELLIPSE" "SPLINE" "LWPOLYLINE" "POLYLINE"))
)

(defun cae-as-point (p)
  (cond
    ((= (type p) 'VARIANT)
     (cae-as-point (vlax-safearray->list (vlax-variant-value p))))
    ((and (= (type p) 'LIST) (>= (length p) 3))
     (list (float (car p)) (float (cadr p)) (float (caddr p))))
    ((and (= (type p) 'LIST) (= (length p) 2))
     (list (float (car p)) (float (cadr p)) 0.0))
    (T nil)
  )
)

(defun cae-curve-closed-p (ent / ed et flags sp ep)
  (setq ed (entget ent) et (cdr (assoc 0 ed)))
  (cond
    ((= et "CIRCLE") T)
    ((member et '("LINE" "ARC")) nil)
    ((member et '("LWPOLYLINE" "POLYLINE"))
     (setq flags (if (assoc 70 ed) (cdr (assoc 70 ed)) 0))
     (/= 0 (logand flags 1)))
    ((= et "SPLINE")
     (setq flags (if (assoc 70 ed) (cdr (assoc 70 ed)) 0))
     (/= 0 (logand flags 3)))
    ((= et "ELLIPSE")
     (setq sp (vlax-curve-getStartParam ent)
           ep (vlax-curve-getEndParam ent))
     (< (abs (- (abs (- ep sp)) (* 2.0 pi))) 0.05))
    (T nil)
  )
)

;;; 沿曲线参数采样。闭合曲线的末点回到起点，符号才能绕完整圈。
(defun cae-sample-boundary-curve (ent / et sp ep n i raw p pts)
  (setq et (cdr (assoc 0 (entget ent))))
  (if (not (cae-boundary-curve-p et))
    nil
    (if (vl-catch-all-error-p
          (vl-catch-all-apply 'vlax-curve-getStartParam (list ent)))
      nil
      (progn
        (setq sp (vlax-curve-getStartParam ent)
              ep (vlax-curve-getEndParam ent)
              n (if (= et "LINE") 1 (if (cae-curve-closed-p ent) 32 16))
              i 0 pts nil)
        (if (< (abs (- ep sp)) 1e-12)
          nil
          (progn
            (while (<= i n)
              (setq raw (vl-catch-all-apply 'vlax-curve-getPointAtParam
                          (list ent (+ sp (* (/ (float i) (float n)) (- ep sp))))))
              (if (not (vl-catch-all-error-p raw))
                (progn
                  (setq p (cae-as-point raw))
                  (if p (setq pts (append pts (list p))))
                )
              )
              (setq i (1+ i))
            )
            (if (>= (length pts) 2) pts nil)
          )
        )
      )
    )
  )
)

;;; 将一条曲线实体采样为点列（供环拼合）
(defun cae-curve-ent-to-pts (subEnt / eType pMid)
  (setq eType (cdr (assoc 0 (entget subEnt))))
  (cond
    ((= eType "LINE")
     (list (vlax-curve-getStartPoint subEnt) (vlax-curve-getEndPoint subEnt)))
    ((member eType '("ARC" "CIRCLE" "SPLINE" "ELLIPSE" "LWPOLYLINE"))
     (setq pMid (vlax-curve-getPointAtParam subEnt
                   (* 0.5 (+ (vlax-curve-getStartParam subEnt)
                             (vlax-curve-getEndParam subEnt)))))
     (sample-3pt-arc-3d (vlax-curve-getStartPoint subEnt)
                        pMid
                        (vlax-curve-getEndPoint subEnt) 16))
    (T nil)
  )
)

;;; 提取板壳闭合边界环三维点列（外环 OUTER / 内孔 INNER）
;;; 支持 REGION、EXTRUDEDSURFACE 等（后者常需二次炸开）
(defun extract-region-loops-3d (ent / eType oldUcs beforeEnt tempClone ssTmp subEnt curves segPts loops curLoop foundNext pEnd ptS ptE maxDiag maxIdx i diag minP maxP resList again e2 mark2)
  (setq eType (cdr (assoc 0 (entget ent))))
  (if (= eType "MESH")
    (list (cons 1000 "V1_NATIVE_MESH"))
    (progn
      (setq oldUcs (getvar "WORLDUCS"))
      (if (= oldUcs 0) (command "_.UCS" "_W"))
      
      (setq beforeEnt (entlast))
      (command "_.COPY" ent "" '(0.0 0.0 0.0) '(0.0 0.0 0.0))
      (setq tempClone (entlast))
      (setq curves nil ssTmp (ssadd) again nil)
      
      (if (not (equal beforeEnt tempClone))
        (progn
          (if (/= eType "3DFACE") (command "_.EXPLODE" tempClone))
          (setq subEnt (entnext beforeEnt))
          (while subEnt
            (ssadd subEnt ssTmp)
            (setq eType (cdr (assoc 0 (entget subEnt))))
            (cond
              ((member eType '("LINE" "ARC" "CIRCLE" "SPLINE" "ELLIPSE" "LWPOLYLINE"))
               (if (setq segPts (cae-curve-ent-to-pts subEnt))
                 (setq curves (append curves (list segPts)))
               )
              )
              ((or (= eType "REGION") (cae-modern-surface-p eType))
               (setq again (cons subEnt again))
              )
            )
            (setq subEnt (entnext subEnt))
          )
          ;; EXTRUDEDSURFACE → REGION / 曲面 → 再炸成边
          (foreach e2 again
            (if (and e2 (entget e2))
              (progn
                (setq mark2 (entlast))
                (command "_.EXPLODE" e2)
                (setq subEnt (entnext mark2))
                (while subEnt
                  (ssadd subEnt ssTmp)
                  (setq eType (cdr (assoc 0 (entget subEnt))))
                  (if (member eType '("LINE" "ARC" "CIRCLE" "SPLINE" "ELLIPSE" "LWPOLYLINE"))
                    (if (setq segPts (cae-curve-ent-to-pts subEnt))
                      (setq curves (append curves (list segPts)))
                    )
                  )
                  (setq subEnt (entnext subEnt))
                )
              )
            )
          )
          (if (> (sslength ssTmp) 0) (command "_.ERASE" ssTmp ""))
        )
      )
      (if (= oldUcs 0) (command "_.UCS" "_P"))
      
      ;; 拼合闭合环
      (setq loops nil)
      (while curves
        (setq curLoop (car curves) curves (cdr curves) foundNext T)
        (while (and foundNext curves)
          (setq foundNext nil pEnd (last curLoop) i 0)
          (while (and (< i (length curves)) (not foundNext))
            (setq segPts (nth i curves) ptS (car segPts) ptE (last segPts))
            (cond
              ((< (distance pEnd ptS) 1e-3)
               (setq curLoop (append curLoop (cdr segPts)) foundNext T))
              ((< (distance pEnd ptE) 1e-3)
               (setq curLoop (append curLoop (cdr (reverse segPts))) foundNext T))
            )
            (if foundNext
              (setq curves (append (cae-subseq curves 0 i) (cae-subseq curves (1+ i) nil)))
              (setq i (1+ i))
            )
          )
        )
        (setq loops (append loops (list curLoop)))
      )
      
      (setq maxDiag -1.0 maxIdx 0 i 0)
      (foreach lp loops
        (setq minP (apply 'mapcar (cons 'min lp)) maxP (apply 'mapcar (cons 'max lp)))
        (setq diag (distance minP maxP))
        (if (> diag maxDiag) (setq maxDiag diag maxIdx i))
        (setq i (1+ i))
      )
      
      (setq resList (list (cons 1000 "V1_PLANAR_3D") (cons 1070 (length loops))))
      (setq i 0)
      (foreach lp loops
        (setq resList (append resList
          (list (cons 1000 (if (= i maxIdx) "OUTER" "INNER"))
                (cons 1070 (length lp)))
          (mapcar '(lambda (p) (cons 1010 p)) lp)))
        (setq i (1+ i))
      )
      resList
    )
  )
)

;;; 创建板壳属性整体块 -> 放入 CAE_VIS_SEC
(defun create-shell-prop-block (cenPt normVec diagLen theoryType thick offZ matName / sz nEnd labelPt labelStr blkDefName blkRef)
  (cae-vis-unlock)
  (setq sz (* (max (* diagLen 0.10) 80.0) *CAE_SCALE_SEC*))
  
  (entmake (list '(0 . "BLOCK") '(2 . "*U") '(70 . 1) '(10 0.0 0.0 0.0)))
  (setq nEnd (vec-scale normVec (* sz 1.3)))
  (entmake (list '(0 . "LINE") '(8 . "0") '(62 . 6) '(10 0.0 0.0 0.0) (cons 11 nEnd)))
  (entmake (list '(0 . "CIRCLE") '(8 . "0") '(62 . 6) (cons 10 nEnd) (cons 40 (* sz 0.12))))
  
  (setq labelPt (vec-add nEnd (vec-scale normVec (* sz 0.15))))
  (setq labelStr (strcat "[" theoryType "] t=" (rtos thick 2 1) " off=" (rtos offZ 2 1) " (" matName ")"))
  (entmake (list '(0 . "TEXT") '(8 . "0") '(62 . 6) (cons 10 labelPt) (cons 40 (* sz 0.22)) (cons 1 labelStr)))
  
  (setq blkDefName (entmake '((0 . "ENDBLK"))))
  (setq blkRef (entmakex (list '(0 . "INSERT") '(8 . "CAE_VIS_SEC") (cons 2 blkDefName) (cons 10 cenPt))))
  (cae-vis-lock)
  blkRef
)

;;; ====================================================================
;;; 板壳属性与约束模块 - 代码块 2/3：SETSHELLSEC 命令与约束符号块
;;; ====================================================================

;;; 命令：SETSHELLSEC - 批量设置板壳截面（单元类型、厚度、偏置与材料）
(defun c:SETSHELLSEC (/ ss thChoice theoryType thick offChoice offZ matChoice matName i ent entHandle info cenPt normVec diagLen visBlk visHandle geomRecords nSet nSkip)
  (vl-load-com)
  (register-shell-prop-app)
  (princ (_T "\n请选择要设置属性的板壳面片 (MESH / REGION / SURFACE / EXTRUDEDSURFACE / …，支持框选): "
         "\nSelect shell faces for properties (MESH / REGION / SURFACE / EXTRUDEDSURFACE / …, window OK): "))
  (setq ss (ssget (list (cons 0 (cae-shell-type-filter)))))
  
  (if ss
    (progn
      (initget "Shell3D PlaneStress PlaneStrain")
      (setq thChoice (getkword (_T "\n分析单元 Shell3D=三维板壳, PlaneStress=平面应力, PlaneStrain=平面应变 [Shell3D/PlaneStress/PlaneStrain] <Shell3D>: "
                               "\nElement theory [Shell3D/PlaneStress/PlaneStrain] <Shell3D>: ")))
      (if (not thChoice) (setq thChoice "Shell3D"))
      (setq theoryType (cond ((= thChoice "PlaneStress") "PLANE_STRESS")
                             ((= thChoice "PlaneStrain") "PLANE_STRAIN")
                             (T "SHELL_3D")))
      
      (setq thick (getreal (_T "\n板壳厚度 Thickness (mm) <10.0>: " "\nShell thickness (mm) <10.0>: ")))
      (if (not thick) (setq thick 10.0))
      
      (initget "Yes No")
      (setq offChoice (getkword (_T "\n是否设置中面偏置? [Yes/No] <No>: "
                                    "\nSet mid-surface offset? [Yes/No] <No>: ")))
      (if (not offChoice) (setq offChoice "No"))
      (if (= offChoice "Yes")
        (progn
          (initget "Mid Top Bottom Custom")
          (setq offChoice (getkword (_T "\n中面偏置 Mid=板中, Top=板顶, Bottom=板底, Custom=自定义 [Mid/Top/Bottom/Custom] <Mid>: "
                                    "\nMid-surface offset [Mid/Top/Bottom/Custom] <Mid>: ")))
          (if (not offChoice) (setq offChoice "Mid"))
          (cond
            ((= offChoice "Mid")    (setq offZ 0.0))
            ((= offChoice "Top")    (setq offZ (* -0.5 thick)))
            ((= offChoice "Bottom") (setq offZ (* 0.5 thick)))
            ((= offChoice "Custom") (setq offZ (getreal (_T "\n法向偏置距离 (mm) <0.0>: " "\nNormal offset (mm) <0.0>: "))) (if (not offZ) (setq offZ 0.0)))
          )
        )
        (setq offZ 0.0)
      )
      
      (initget "Q235B Q355B 45Steel Al6061 Concrete Other")
      (setq matChoice (getkword (_T "\n材料牌号 Other=自定义 [Q235B/Q355B/45Steel/Al6061/Concrete/Other] <Q355B>: "
                                "\nMaterial [Q235B/Q355B/45Steel/Al6061/Concrete/Other] <Q355B>: ")))
      (if (not matChoice) (setq matChoice "Q355B"))
      (if (= matChoice "Other")
        (progn (setq matName (getstring T (_T "\n自定义材料名称: " "\nCustom material name: "))) (if (= matName "") (setq matName "Custom_Mat")))
        (setq matName matChoice)
      )
      
      (setq i 0 nSet 0 nSkip 0)
      (cae-vis-begin-batch)
      (while (< i (sslength ss))
        (setq ent (ssname ss i))
        ;; 开口多段线（回转母线）不是板：清掉误写的厚度，不追加
        (if (not (cae-shell-plate-p ent))
          (progn
            (cae-clear-shell-prop ent)
            (setq nSkip (1+ nSkip))
          )
          (progn
            (setq entHandle (cdr (assoc 5 (entget ent))))
            (setq info (get-shell-center-normal ent))
            (setq cenPt (car info) normVec (cadr info) diagLen (caddr info))
            ;; 覆盖：先删旧符号并清空 MY_CAE_SHELL_PROP，再写唯一一条厚度/偏置
            (cae-clear-shell-prop ent)
            (setq visBlk (create-shell-prop-block cenPt normVec diagLen theoryType thick offZ matName))
            (setq visHandle (cdr (assoc 5 (entget visBlk))))
            (entmod (append (entget ent)
                            (list (list -3 (list "MY_CAE_SHELL_PROP"
                                                 (cons 1000 theoryType)
                                                 (cons 1040 thick)
                                                 (cons 1040 offZ)
                                                 (cons 1000 matName)
                                                 (cons 1005 visHandle))))))
            (setq geomRecords (append (list "MY_CAE_SHELL_GEOM" (cons 1013 normVec)) (extract-region-loops-3d ent)))
            (entmod (append (entget ent) (list (list -3 geomRecords))))
            (entupd ent)
            (entmod (append (entget visBlk) (list (list -3 (list "MY_CAE_SHELL_PROP" (cons 1005 entHandle))))))
            (setq nSet (1+ nSet))
          )
        )
        (setq i (1+ i))
      )
      (cae-vis-end-batch)
      (princ (strcat (_T "\n[成功] 已覆盖 " "\n[OK] Overwrote properties on ") (itoa nSet)
                 (_T " 块板 [" " shell(s) [") theoryType ", t=" (rtos thick 2 1) "mm, " matName "]"
                 (if (> nSkip 0)
                   (strcat (_T "；跳过并清除 " "; skipped/cleared ") (itoa nSkip)
                           (_T " 个非板（开口多段线等）。" " non-plate(s) (open polylines)."))
                   "")))
    )
  )
  (princ)
)

;;; 绘制板壳边约束或面约束整体符号 -> 放入 CAE_VIS_BC (青色=4)
(defun cae-poly-length (pts / i len)
  (setq len 0.0 i 0)
  (while (< i (1- (length pts)))
    (setq len (+ len (distance (nth i pts) (nth (1+ i) pts)))
          i (1+ i))
  )
  len
)

(defun cae-pts-closed-p (pts / len)
  (setq len (cae-poly-length pts))
  (and (> (length pts) 2)
       (> len 1e-9)
       (<= (distance (car pts) (last pts)) (max 1e-3 (* 1e-4 len))))
)

(defun cae-point-along (pts dist / i a b seg walked tt)
  (cond
    ((or (not pts) (<= dist 0.0)) (car pts))
    (T
     (setq i 0 walked 0.0 a nil)
     (while (and (< i (1- (length pts))) (null a))
       (setq b (nth (1+ i) pts)
             seg (distance (nth i pts) b))
       (if (or (>= (+ walked seg) (- dist 1e-9)) (< seg 1e-15))
         (progn
           (setq tt (if (< seg 1e-15) 0.0 (/ (- dist walked) seg)))
           (if (< tt 0.0) (setq tt 0.0))
           (if (> tt 1.0) (setq tt 1.0))
           (setq a (mapcar '(lambda (u v) (+ u (* tt (- v u)))) (nth i pts) b))
         )
         (setq walked (+ walked seg)
               i (1+ i))
       )
     )
     (if a a (last pts)))
  )
)

;;; 开口曲线 3–5 个（含两端），间距至少两个符号长；封闭曲线恰好 5 个。
(defun cae-edge-bc-stations (pts / len gap n i out sc)
  (setq len (cae-poly-length pts))
  (if (or (not pts) (< len 1e-9))
    (if pts (list (car pts)) nil)
    (progn
      (setq sc (if (and *CAE_SCALE_BC* (> *CAE_SCALE_BC* 0.0)) *CAE_SCALE_BC* 1.0)
            out nil
            i 0)
      (if (cae-pts-closed-p pts)
        (while (< i 5)
          (setq out (append out (list (cae-point-along pts (* len (/ (float i) 5.0)))))
                i (1+ i))
        )
        (progn
          (setq gap (* 2.0 (max (* len 0.08) 60.0) sc))
          (cond
            ((>= (/ len 4.0) gap) (setq n 5))
            ((>= (/ len 3.0) gap) (setq n 4))
            (T (setq n 3))
          )
          (while (< i n)
            (setq out (append out
                              (list (cae-point-along pts (* len (/ (float i) (float (1- n)))))))
                  i (1+ i))
          )
        )
      )
      out
    )
  )
)

(defun create-shell-bc-block (ptsList bcScope uVecs rVecs uMask rMask / pOrigin totalLen i sz locPts stations pt u r blkDefName blkRef labelPt labelStr)
  (unlock-all-cae-layers)
  (setq pOrigin (car ptsList))
  (if (= bcScope "FACE_BC")
    (setq sz (* 120.0 *CAE_SCALE_BC*)
          locPts '((0.0 0.0 0.0))
          stations '((0.0 0.0 0.0)))
    (progn
      (setq totalLen (cae-poly-length ptsList))
      (setq sz (* (max (* totalLen 0.08) 60.0) *CAE_SCALE_BC*))
      (setq locPts (mapcar '(lambda (p) (vec-sub p pOrigin)) ptsList))
      (setq stations (mapcar '(lambda (p) (vec-sub p pOrigin))
                             (cae-edge-bc-stations ptsList)))
    )
  )

  (entmake (list '(0 . "BLOCK") '(2 . "*U") '(70 . 1) '(10 0.0 0.0 0.0)))

  (if (and (/= bcScope "FACE_BC") (> (length locPts) 1))
    (progn
      (setq i 0)
      (while (< i (1- (length locPts)))
        (entmake (list '(0 . "LINE") '(8 . "0") '(62 . 4)
                       (cons 10 (nth i locPts)) (cons 11 (nth (1+ i) locPts))))
        (setq i (1+ i))
      )
    )
  )

  (foreach pt stations
    (entmake (list '(0 . "CIRCLE") '(8 . "0") '(62 . 4) (cons 10 pt) (cons 40 (* sz 0.14))))
    (foreach u uVecs
      (entmake (list '(0 . "LINE") '(8 . "0") '(62 . 6)
                     (cons 10 pt) (cons 11 (vec-add pt (vec-scale u (* sz 1.2))))))
    )
    (foreach r rVecs
      (entmake (list '(0 . "LINE") '(8 . "0") '(62 . 2)
                     (cons 10 pt) (cons 11 (vec-add pt (vec-scale r (* sz 1.4))))))
    )
  )

  (setq labelPt (if stations (nth (/ (length stations) 2) stations) '(0.0 0.0 0.0)))
  (setq labelStr (strcat bcScope " U:" uMask " R:" rMask))
  (entmake (list '(0 . "TEXT") '(8 . "0") '(62 . 4) (cons 10 labelPt) (cons 40 (* sz 0.25)) (cons 1 labelStr)))

  (setq blkDefName (entmake '((0 . "ENDBLK"))))
  (setq blkRef (entmakex (list '(0 . "INSERT") '(8 . "CAE_VIS_BC") (cons 2 blkDefName) (cons 10 pOrigin))))
  (lock-all-cae-layers)
  blkRef
)

;;; ====================================================================
;;; 板壳属性与约束模块 - 代码块 3/3：SETSHELLBC 与 DELSHELLBC 命令
;;; ====================================================================

(defun cae-ents-after (mark / e out)
  (setq e (entnext mark) out nil)
  (while e
    (setq out (cons e out)
          e (entnext e))
  )
  out
)

(defun cae-layer-locked-p (name / en flags)
  (setq en (tblobjname "LAYER" name))
  (if en
    (progn
      (setq flags (cdr (assoc 70 (entget en))))
      (= 4 (logand flags 4))
    )
    nil
  )
)

(defun cae-ent-invisible (ent flag / obj)
  (setq obj (vlax-ename->vla-object ent))
  (vl-catch-all-apply 'vla-put-Visible
    (list obj (if flag :vlax-false :vlax-true)))
  (redraw ent)
)

(defun cae-paint-pick-edge (ent / ed)
  (setq ed (entget ent))
  (if (assoc 8 ed)
    (setq ed (subst '(8 . "CAE_EDGE_PICK") (assoc 8 ed) ed))
    (setq ed (append ed '((8 . "CAE_EDGE_PICK"))))
  )
  (if (assoc 62 ed)
    (setq ed (subst '(62 . 1) (assoc 62 ed) ed))
    (setq ed (append ed '((62 . 1))))
  )
  (entmod ed)
  (entupd ent)
)

(defun cae-erase-ss (ss / i)
  (if ss
    (progn
      (setq i 0)
      (while (< i (sslength ss))
        (if (entget (ssname ss i)) (entdel (ssname ss i)))
        (setq i (1+ i))
      )
    )
  )
)

;;; 复制面并炸开，得到可点选的边界曲线（红，图层 CAE_EDGE_PICK）。原面不动。
(defun cae-materialize-face-edges (face / echo faceLay faceLocked sent pending curves pass born e eType ss)
  (setq echo (getvar "CMDECHO"))
  (setvar "CMDECHO" 0)
  (setq faceLay (cdr (assoc 8 (entget face)))
        faceLocked (cae-layer-locked-p faceLay))
  (if faceLocked (cae-set-layer-lock faceLay nil))
  (cae-ensure-layer "CAE_EDGE_PICK" 1)
  (cae-set-layer-lock "CAE_EDGE_PICK" nil)
  ;; 哨兵留在数据库末尾之前，后面只走本次复制/炸开产生的实体
  (setq sent (entmakex (list '(0 . "POINT") '(8 . "CAE_EDGE_PICK") '(62 . 1) '(10 0.0 0.0 0.0))))
  (command "_.COPY" face "" '(0.0 0.0 0.0) '(0.0 0.0 0.0))
  (setq pending (cae-ents-after sent)
        curves nil
        pass 0)
  (while (and pending (< pass 4))
    (foreach e pending
      (if (entget e)
        (progn
          (cae-paint-pick-edge e)
          (command "_.EXPLODE" e)
        )
      )
    )
    (setq born (cae-ents-after sent)
          pending nil)
    (foreach e born
      (if (and (entget e) (not (member e curves)))
        (progn
          (setq eType (cdr (assoc 0 (entget e))))
          (cond
            ((cae-boundary-curve-p eType)
             (setq curves (cons e curves)))
            ((or (= eType "REGION") (cae-modern-surface-p eType)
                 (member eType '("3DSOLID" "BODY" "MESH")))
             (setq pending (cons e pending)))
            (T (entdel e))
          )
        )
      )
    )
    (setq pass (1+ pass))
  )
  (foreach e pending
    (if (entget e) (entdel e))
  )
  (if (and sent (entget sent)) (entdel sent))
  (setq ss (ssadd))
  (foreach e curves
    (if (entget e)
      (progn
        (cae-paint-pick-edge e)
        (ssadd e ss)
        (redraw e 3)
      )
    )
  )
  (if faceLocked (cae-set-layer-lock faceLay T))
  (setvar "CMDECHO" echo)
  (if (and ss (> (sslength ss) 0)) ss nil)
)

;;; 命令：SETSHELLBC - 先选面，再从临时显示的边界中选一条施加约束
(defun c:SETSHELLBC (/ selMain mainEnt mainType mainHandle edgeSS selEdge edgeEnt edgeType pts bcType pA pB pMid v1 v2 nVec sVec rAxis uVecs rVecs uTriad rTriad visBlk visHandle oldXd newRecs ptPairs)
  (vl-load-com)
  (register-shell-bc-app)

  (setq selMain (entsel (_T "\n[第1步] 请选择板壳面 (MESH / REGION / SURFACE / …): "
                             "\n[Step 1] Select a shell face (MESH / REGION / SURFACE / …): ")))
  (if selMain
    (progn
      (setq mainEnt (car selMain))
      (setq mainType (cdr (assoc 0 (entget mainEnt))))
      (setq mainHandle (cdr (assoc 5 (entget mainEnt))))

      (if (cae-shell-type-p mainType)
        (progn
          (princ (_T "\n正在提取边界…" "\nExtracting boundaries…"))
          (setq edgeSS (cae-materialize-face-edges mainEnt))
          (if (not edgeSS)
            (princ (_T "\n[错误] 未能从该面提取出边界。" "\n[Error] No boundary curves from this face."))
            (progn
              (cae-ent-invisible mainEnt T)
              (princ (strcat (_T "\n已显示 " "\nShowing ") (itoa (sslength edgeSS))
                             (_T " 条红色边界。" " red boundary curve(s).")))
              (setq selEdge (entsel (_T "\n[第2步] 选择一条红色边界: "
                                         "\n[Step 2] Select one red boundary: ")))
              (cae-ent-invisible mainEnt nil)
              (if (and selEdge (ssmemb (car selEdge) edgeSS))
                (progn
                  (setq edgeEnt (car selEdge))
                  (setq edgeType (cdr (assoc 0 (entget edgeEnt))))
                  (setq pts (cae-sample-boundary-curve edgeEnt))
                )
                (if selEdge
                  (princ (_T "\n[错误] 请选择刚显示的红色边界。" "\n[Error] Pick one of the red boundary curves."))
                )
              )
              (cae-erase-ss edgeSS)
            )
          )

          (if pts
            (progn
              (setq uVecs nil rVecs nil)
              (initget "FixAll PinPlane SlideLine RotAxis")
              (setq bcType (getkword (_T "\n约束模式 FixAll=全固支, PinPlane=面内滑移, SlideLine=沿线滑移, RotAxis=绕轴转动 [FixAll/PinPlane/SlideLine/RotAxis] <FixAll>: "
                              "\nBC mode [FixAll/PinPlane/SlideLine/RotAxis] <FixAll>: ")))
              (if (not bcType) (setq bcType "FixAll"))

              (cond
                ((= bcType "FixAll")
                 (setq uVecs '((1.0 0.0 0.0) (0.0 1.0 0.0) (0.0 0.0 1.0)))
                 (setq rVecs '((1.0 0.0 0.0) (0.0 1.0 0.0) (0.0 0.0 1.0)))
                )
                ((= bcType "PinPlane")
                 (setq pA (getpoint (_T "\n请在允许滑移的平面内捕捉第1点: " "\nPick 1st point in sliding plane: ")))
                 (if pA (setq pB (getpoint pA (_T "\n请在平面内捕捉第2点: " "\nPick 2nd point in plane: "))))
                 (if (and pA pB)
                   (progn
                     (setq v1 (vec-sub (trans pB 1 0) (trans pA 1 0)))
                     (setq pMid (getpoint (trans pA 1 0) (_T "\n请在平面内捕捉第3个不共线点: " "\nPick 3rd non-colinear point: ")))
                     (if pMid
                       (progn
                         (setq v2 (vec-sub (trans pMid 1 0) (trans pA 1 0)))
                         (setq nVec (vec-unit (vec-cross v1 v2)))
                         (if nVec (setq uVecs (list nVec)))
                       )
                     )
                   )
                 )
                )
                ((= bcType "SlideLine")
                 (setq pA (getpoint (_T "\n请捕捉允许滑移方向线的第1点: " "\nPick slide-direction point 1: ")))
                 (if pA (setq pB (getpoint pA (_T "\n请捕捉允许滑移方向线的第2点: " "\nPick slide-direction point 2: "))))
                 (if (and pA pB)
                   (progn
                     (setq sVec (vec-unit (vec-sub (trans pB 1 0) (trans pA 1 0))))
                     (if sVec
                       (progn
                         (setq uTriad (make-local-basis sVec))
                         (setq uVecs (list (cadr uTriad) (caddr uTriad)))
                       )
                     )
                   )
                 )
                )
                ((= bcType "RotAxis")
                 (setq pA (getpoint (_T "\n请捕捉受限旋转轴线的第1点: " "\nPick rotation-axis point 1: ")))
                 (if pA (setq pB (getpoint pA (_T "\n请捕捉受限旋转轴线的第2点: " "\nPick rotation-axis point 2: "))))
                 (if (and pA pB)
                   (progn
                     (setq rAxis (vec-unit (vec-sub (trans pB 1 0) (trans pA 1 0))))
                     (if rAxis (setq rVecs (list rAxis)))
                   )
                 )
                )
              )

              (setq uTriad (build-full-triad uVecs))
              (setq rTriad (build-full-triad rVecs))

              (setq visBlk (create-shell-bc-block pts "EDGE_BC" uVecs rVecs (nth 3 uTriad) (nth 3 rTriad)))
              (setq visHandle (cdr (assoc 5 (entget visBlk))))

              (setq ptPairs (mapcar '(lambda (p) (cons 1010 p)) pts))
              (setq oldXd (cdr (cadr (assoc -3 (entget mainEnt '("MY_CAE_SHELL_BC"))))))
              (setq newRecs (append oldXd
                (list (cons 1000 "EDGE_BC")
                      (cons 1000 (nth 3 uTriad)) (cons 1013 (nth 0 uTriad)) (cons 1013 (nth 1 uTriad)) (cons 1013 (nth 2 uTriad))
                      (cons 1000 (nth 3 rTriad)) (cons 1013 (nth 0 rTriad)) (cons 1013 (nth 1 rTriad)) (cons 1013 (nth 2 rTriad))
                      (cons 1005 visHandle)
                      (cons 1070 (length pts)))
                ptPairs))

              (entmod (append (entget mainEnt) (list (list -3 (cons "MY_CAE_SHELL_BC" newRecs)))))
              (entupd mainEnt)
              (entmod (append (entget visBlk) (list (list -3 (list "MY_CAE_SHELL_BC" (cons 1005 mainHandle))))))
              (princ (strcat (_T "\n[成功] 已在边界 " "\n[OK] Boundary ") edgeType
                             (_T " 上施加约束 U:" " BC U:") (nth 3 uTriad) " | R:" (nth 3 rTriad)))
            )
            (if (and selEdge (cae-boundary-curve-p edgeType))
              (princ (_T "\n[错误] 未能读取这条边界曲线。" "\n[Error] Could not sample that boundary curve."))
            )
          )
        )
        (princ (strcat (_T "\n[错误] 不支持的面片实体类型: " "\n[Error] Unsupported face type: ") mainType))
      )
    )
  )
  (princ)
)

;;; 命令：DELSHELLBC - 双向清除板壳上的所有约束及支座符号
(defun c:DELSHELLBC (/ ss i ent entData entType xdata appData idx numPts visHandle oldBlk targetEnt)
  (unlock-all-cae-layers)
  (princ (_T "\n请选择要清除约束的【板壳面片】或【青色支座整体符号】: "
         "\nSelect shell face(s) or cyan BC symbol(s) to clear: "))
  (setq ss (ssget (list (cons 0 (cae-shell-type-filter-ins)))))
  (if ss
    (progn
      (setq i 0)
      (while (< i (sslength ss))
        (setq ent (ssname ss i))
        (setq entData (entget ent '("MY_CAE_SHELL_BC")))
        (setq entType (cdr (assoc 0 entData)))
        (setq xdata (assoc -3 entData))
        (if xdata
          (progn
            (setq appData (cdr (cadr xdata)))
            (if (/= entType "INSERT")
              (progn
                (setq idx 0)
                (while (< idx (length appData))
                  (setq visHandle (cdr (nth (+ idx 9) appData)))
                  (setq numPts    (cdr (nth (+ idx 10) appData)))
                  (if (and visHandle (setq oldBlk (handent visHandle)))
                    (if (entget oldBlk) (entdel oldBlk))
                  )
                  (setq idx (+ idx 11 numPts))
                )
                (entmod (append (entget ent) (list (list -3 (list "MY_CAE_SHELL_BC")))))
                (entupd ent)
              )
              (progn
                (setq targetEnt (handent (cdr (nth 0 appData))))
                (if (and targetEnt (entget targetEnt))
                  (progn
                    (entmod (append (entget targetEnt) (list (list -3 (list "MY_CAE_SHELL_BC")))))
                    (entupd targetEnt)
                  )
                )
                (entdel ent)
              )
            )
          )
        )
        (setq i (1+ i))
      )
      (princ (_T "\n[清除完成] 所选板壳约束与支座符号已同步销毁。"
         "\n[Done] Shell BCs and symbols removed."))
    )
  )
  (lock-all-cae-layers)
  (princ)
)

;;; ====================================================================
;;; 点焊 / 满焊  MY_CAE_SPOT_WELD / MY_CAE_SEAM_WELD + CAE_VIS_WELD
;;; 点焊载体：POINT（层 0）；满焊载体：LINE/LWPOLYLINE/ARC（真实几何）
;;; XData 点焊: 1000=SPOT, 1040=直径mm, 1000=FE类型, 1005=VIS
;;; XData 满焊: 1000=FILLET|BUTT, 1040=焊脚mm, 1040=步长mm, 1005=VIS
;;; ====================================================================

(defun cae-last (lst)
  (while (cdr lst) (setq lst (cdr lst)))
  (car lst)
)

(defun cae-make-anon-blk (ents / name)
  ;; 匿名块名必须以 *U 开头
  (setq name (strcat "*U" (rtos (* 1000000.0 (rem (getvar "CDATE") 1.0)) 2 0)))
  (entmake (list '(0 . "BLOCK") (cons 2 name) '(10 0.0 0.0 0.0) '(70 . 1)))
  (foreach e ents (entmake e))
  (entmake '((0 . "ENDBLK")))
  name
)

;;; 点焊可视化：黄圈 + 十字
(defun create-spot-weld-vis (pt dia / r blkName blkRef)
  (cae-vis-unlock)
  (setq r (max 1.2 (* 0.35 dia)))
  (setq blkName (cae-make-anon-blk
    (list
      (list '(0 . "CIRCLE") '(8 . "0") '(62 . 2) '(10 0.0 0.0 0.0) (cons 40 r))
      (list '(0 . "LINE") '(8 . "0") '(62 . 2)
            (cons 10 (list (- r) 0.0 0.0)) (cons 11 (list r 0.0 0.0)))
      (list '(0 . "LINE") '(8 . "0") '(62 . 2)
            (cons 10 (list 0.0 (- r) 0.0)) (cons 11 (list 0.0 r 0.0)))
    )))
  (setq blkRef (entmakex (list '(0 . "INSERT") '(8 . "CAE_VIS_WELD")
                               (cons 2 blkName) (cons 10 pt))))
  (cae-vis-lock)
  blkRef
)

(defun attach-spot-weld-xdata (ptEnt dia feType visHandle /)
  (entmod (append (entget ptEnt)
                  (list (list -3 (list "MY_CAE_SPOT_WELD"
                    (cons 1000 "SPOT")
                    (cons 1040 dia)
                    (cons 1000 feType)
                    (cons 1005 visHandle))))))
  (entupd ptEnt)
)

(defun create-one-spot-weld (ptWcs dia feType / ptEnt visEnt visH ptH)
  (setq ptEnt (entmakex (list '(0 . "POINT") '(8 . "0") (cons 10 ptWcs))))
  (setq visEnt (create-spot-weld-vis ptWcs dia))
  (setq visH (cdr (assoc 5 (entget visEnt)))
        ptH  (cdr (assoc 5 (entget ptEnt))))
  (attach-spot-weld-xdata ptEnt dia feType visH)
  (entmod (append (entget visEnt)
                  (list (list -3 (list "MY_CAE_SPOT_WELD" (cons 1005 ptH))))))
  ptEnt
)

(defun sample-line-by-spacing (p1 p2 spacing / len n i pts d)
  (setq len (distance p1 p2))
  (if (< len 1e-9)
    (list p1)
    (progn
      (if (or (not spacing) (<= spacing 0.0)) (setq spacing len))
      (setq n (max 1 (fix (1+ (/ len spacing))))
            i 0 pts nil)
      (while (<= i n)
        (setq d (if (= n 0) 0.0 (/ (float i) (float n))))
        (setq pts (append pts (list (mapcar '(lambda (a b) (+ a (* d (- b a)))) p1 p2))))
        (setq i (1+ i))
      )
      pts
    )
  )
)

(defun c:SETSPOTWELD (/ mode dia feChoice feType p1 p2 spacing pts pt nOk)
  (register-all-cae-apps)
  (initget "Single Along")
  (setq mode (getkword (_T "\n布置方式 Single=单点, Along=沿线间距 [Single/Along] <Single>: "
                           "\nMode [Single/Along] <Single>: ")))
  (if (not mode) (setq mode "Single"))
  (setq dia (getreal (_T "\n焊核直径 (mm) <5.0>: " "\nNugget diameter (mm) <5.0>: ")))
  (if (not dia) (setq dia 5.0))
  ;; Acm / Cweld / Rbe — 缩写互不冲突
  (initget "Acm Cweld Rbe")
  (setq feChoice (getkword (_T "\n焊点单元 [Acm/Cweld/Rbe] <Acm>: "
                               "\nSpot FE type [Acm/Cweld/Rbe] <Acm>: ")))
  (if (not feChoice) (setq feChoice "Acm"))
  (setq feType (cond ((= feChoice "Cweld") "CWELD")
                     ((= feChoice "Rbe") "RBE2")
                     (T "ACM")))
  (setq nOk 0)
  (cond
    ((= mode "Along")
     (setq p1 (getpoint (_T "\n请捕捉起点（建议 OSNAP）: " "\nPick start (OSNAP): ")))
     (if p1 (setq p2 (getpoint p1 (_T "\n请捕捉终点: " "\nPick end: "))))
     (if (and p1 p2)
       (progn
         (setq spacing (getreal (_T "\n间距 Spacing (mm) <25.0>: " "\nSpacing (mm) <25.0>: ")))
         (if (not spacing) (setq spacing 25.0))
         (setq p1 (trans p1 1 0) p2 (trans p2 1 0)
               pts (sample-line-by-spacing p1 p2 spacing))
         (cae-vis-begin-batch)
         (foreach pt pts
           (create-one-spot-weld pt dia feType)
           (setq nOk (1+ nOk))
         )
         (cae-vis-end-batch)
       )
     )
    )
    (T
     (setq p1 (getpoint (_T "\n请捕捉焊点位置（建议 OSNAP）: " "\nPick spot (OSNAP): ")))
     (if p1
       (progn
         (cae-vis-begin-batch)
         (create-one-spot-weld (trans p1 1 0) dia feType)
         (cae-vis-end-batch)
         (setq nOk 1)
       )
     )
    )
  )
  (if (> nOk 0)
    (princ (strcat (_T "\n[成功] 点焊 " "\n[OK] Spot welds ") (itoa nOk)
                   " Ø" (rtos dia 2 2) " / " feType))
    (princ (_T "\n[取消] 未创建点焊。" "\n[Cancel] No spot welds created."))
  )
  (princ)
)

(defun c:DELSPOTWELD (/ ss i ent ed typ xd app visH hostH oldVis host)
  (unlock-vis-layer)
  (princ (_T "\n请选择【点焊 POINT】或【黄色点焊符号】: "
             "\nSelect spot POINT(s) or yellow spot symbol(s): "))
  (setq ss (ssget '((0 . "POINT,INSERT"))))
  (if ss
    (progn
      (setq i 0)
      (while (< i (sslength ss))
        (setq ent (ssname ss i)
              ed (entget ent '("MY_CAE_SPOT_WELD"))
              typ (cdr (assoc 0 ed))
              xd (assoc -3 ed))
        (if xd
          (progn
            (setq app (cdr (cadr xd)))
            (if (= typ "POINT")
              (progn
                (setq visH (cdr (assoc 1005 app)))
                (if (and visH (setq oldVis (handent visH)))
                  (if (entget oldVis) (entdel oldVis))
                )
                (entdel ent)
              )
              (progn
                (setq hostH (cdr (assoc 1005 app)))
                (if (and hostH (setq host (handent hostH)))
                  (if (entget host) (entdel host))
                )
                (entdel ent)
              )
            )
          )
        )
        (setq i (1+ i))
      )
      (princ (_T "\n[清除完成] 点焊已删除。" "\n[Done] Spot welds removed."))
    )
  )
  (lock-vis-layer)
  (princ)
)

(defun refresh-spot-welds (/ ss i ent ed xd app dia fe visH oldVis newVis newH cnt)
  (setq ss (ssget "_X" '((0 . "POINT"))) cnt 0)
  (if ss
    (progn
      (setq i 0)
      (while (< i (sslength ss))
        (setq ent (ssname ss i)
              ed (entget ent '("MY_CAE_SPOT_WELD"))
              xd (assoc -3 ed))
        (if xd
          (progn
            ;; app: 1000 SPOT, 1040 dia, 1000 feType, 1005 vis
            (setq app (cdr (cadr xd))
                  dia (cdr (nth 1 app))
                  fe  (cdr (nth 2 app)))
            (if (not dia) (setq dia 5.0))
            (if (or (not fe) (= fe "SPOT")) (setq fe "ACM"))
            (setq visH (cdr (assoc 1005 app)))
            (if (and visH (setq oldVis (handent visH)))
              (if (entget oldVis) (entdel oldVis))
            )
            (setq newVis (create-spot-weld-vis (cdr (assoc 10 ed)) dia)
                  newH (cdr (assoc 5 (entget newVis))))
            (attach-spot-weld-xdata ent dia fe newH)
            (entmod (append (entget newVis)
                            (list (list -3 (list "MY_CAE_SPOT_WELD"
                              (cons 1005 (cdr (assoc 5 ed))))))))
            (setq cnt (1+ cnt))
          )
        )
        (setq i (1+ i))
      )
    )
  )
  cnt
)

;;; ---------- 满焊轨迹采样 ----------
(defun cae-lwpoly-pts (ed / pts elev)
  (setq elev (if (assoc 38 ed) (cdr (assoc 38 ed)) 0.0) pts nil)
  (foreach it ed
    (if (= (car it) 10)
      (setq pts (append pts (list (list (cadr it) (caddr it) elev))))
    )
  )
  pts
)

(defun cae-arc-sample (ed n / cen r a0 a1 a i pts)
  (setq cen (cdr (assoc 10 ed))
        r   (cdr (assoc 40 ed))
        a0  (* (/ (cdr (assoc 50 ed)) 180.0) pi)
        a1  (* (/ (cdr (assoc 51 ed)) 180.0) pi)
        n   (max 4 n))
  (if (< a1 a0) (setq a1 (+ a1 (* 2.0 pi))))
  (setq i 0 pts nil)
  (while (<= i n)
    (setq a (+ a0 (* (/ (float i) (float n)) (- a1 a0))))
    (setq pts (append pts (list (list (+ (car cen) (* r (cos a)))
                                     (+ (cadr cen) (* r (sin a)))
                                     (if (caddr cen) (caddr cen) 0.0)))))
    (setq i (1+ i))
  )
  pts
)

(defun cae-densify-polyline (verts spacing / out a b seg)
  (if (or (not verts) (not (cdr verts)))
    verts
    (progn
      (setq out (list (car verts)) a (car verts) verts (cdr verts))
      (foreach b verts
        (setq seg (sample-line-by-spacing a b spacing))
        (setq out (append out (cdr seg)))
        (setq a b)
      )
      out
    )
  )
)

(defun cae-entity-path-pts (ent spacing / ed typ p1 p2 pts arcLen n)
  (setq ed (entget ent) typ (cdr (assoc 0 ed)))
  (cond
    ((= typ "LINE")
     (setq p1 (cdr (assoc 10 ed)) p2 (cdr (assoc 11 ed)))
     (sample-line-by-spacing p1 p2 spacing)
    )
    ((= typ "LWPOLYLINE")
     (cae-densify-polyline (cae-lwpoly-pts ed) spacing)
    )
    ((= typ "ARC")
     (setq arcLen (* (cdr (assoc 40 ed))
                     (abs (- (cdr (assoc 51 ed)) (cdr (assoc 50 ed))))
                     (/ pi 180.0)))
     (setq n (max 8 (fix (/ arcLen (if (and spacing (> spacing 0)) spacing 5.0)))))
     (cae-arc-sample ed n)
    )
    (T nil)
  )
)

;;; 锯齿 VIS：匿名块内折线（交替法向偏移）
(defun create-seam-weld-vis (pathPts amp / zig i p0 p1 mid tdir nxy blkName blkRef base ents)
  (cae-vis-unlock)
  (if (or (not pathPts) (< (length pathPts) 2))
    (progn (cae-vis-lock) nil)
    (progn
      (setq amp (if (and amp (> amp 0)) amp 1.5)
            base (car pathPts)
            zig nil i 0)
      (while (< i (1- (length pathPts)))
        (setq p0 (nth i pathPts) p1 (nth (1+ i) pathPts)
              tdir (vec-unit (vec-sub p1 p0)))
        (if tdir
          (progn
            (setq nxy (vec-unit (list (- (cadr tdir)) (car tdir) 0.0)))
            (if (not nxy) (setq nxy '(0.0 1.0 0.0)))
            (setq mid (vec-add
                        (list (* 0.5 (+ (car p0) (car p1)))
                              (* 0.5 (+ (cadr p0) (cadr p1)))
                              (* 0.5 (+ (caddr p0) (caddr p1))))
                        (vec-scale nxy (if (= (rem i 2) 0) amp (- amp)))))
            (setq zig (append zig (list p0 mid)))
          )
        )
        (setq i (1+ i))
      )
      (setq zig (append zig (list (cae-last pathPts))))
      ;; 块坐标相对 base
      (setq ents nil i 0)
      (while (< i (1- (length zig)))
        (setq p0 (vec-sub (nth i zig) base)
              p1 (vec-sub (nth (1+ i) zig) base))
        (setq ents (append ents (list
          (list '(0 . "LINE") '(8 . "0") '(62 . 2)
                (cons 10 p0) (cons 11 p1)))))
        (setq i (1+ i))
      )
      (setq blkName (cae-make-anon-blk ents)
            blkRef (entmakex (list '(0 . "INSERT") '(8 . "CAE_VIS_WELD")
                                   (cons 2 blkName) (cons 10 base))))
      (cae-vis-lock)
      blkRef
    )
  )
)

(defun attach-seam-weld-xdata (pathEnt weldType leg spacing visHandle /)
  (entmod (append (entget pathEnt)
                  (list (list -3 (list "MY_CAE_SEAM_WELD"
                    (cons 1000 weldType)
                    (cons 1040 leg)
                    (cons 1040 spacing)
                    (cons 1005 visHandle))))))
  (entupd pathEnt)
)

(defun c:SETSEAMWELD (/ ss ent ed typ weldChoice weldType leg spacing pathPts visEnt visH pathH)
  (register-all-cae-apps)
  (princ (_T "\n请选择焊缝轨迹 LINE / LWPOLYLINE / ARC（建议 OSNAP 落在钣金棱边）: "
             "\nSelect seam path LINE/LWPOLYLINE/ARC (OSNAP on sheet edge): "))
  (setq ss (ssget '((0 . "LINE,LWPOLYLINE,ARC"))))
  (if (and ss (= (sslength ss) 1))
    (progn
      (setq ent (ssname ss 0) ed (entget ent) typ (cdr (assoc 0 ed)))
      (initget "Fillet Butt")
      (setq weldChoice (getkword (_T "\n焊缝类型 Fillet=角焊, Butt=对接 [Fillet/Butt] <Fillet>: "
                                     "\nSeam type [Fillet/Butt] <Fillet>: ")))
      (if (not weldChoice) (setq weldChoice "Fillet"))
      (setq weldType (strcase weldChoice))
      (setq leg (getreal (_T "\n焊脚尺寸 LegSize (mm) <4.0>: " "\nLeg size (mm) <4.0>: ")))
      (if (not leg) (setq leg 4.0))
      (setq spacing (getreal (_T "\n离散步长 Spacing (mm) <5.0>: " "\nDiscretize spacing (mm) <5.0>: ")))
      (if (not spacing) (setq spacing 5.0))
      ;; 清除旧 VIS
      (setq ed (entget ent '("MY_CAE_SEAM_WELD")))
      (if (assoc -3 ed)
        (progn
          (setq visH (cdr (assoc 1005 (cdr (cadr (assoc -3 ed))))))
          (if (and visH (setq visEnt (handent visH)))
            (progn (cae-vis-unlock) (if (entget visEnt) (entdel visEnt)) (cae-vis-lock))
          )
        )
      )
      (setq pathPts (cae-entity-path-pts ent spacing))
      (if (and pathPts (>= (length pathPts) 2))
        (progn
          (cae-vis-begin-batch)
          (setq visEnt (create-seam-weld-vis pathPts (max 1.2 (* 0.35 leg))))
          (cae-vis-end-batch)
          (if visEnt
            (progn
              (setq visH (cdr (assoc 5 (entget visEnt)))
                    pathH (cdr (assoc 5 (entget ent))))
              (attach-seam-weld-xdata ent weldType leg spacing visH)
              (entmod (append (entget visEnt)
                              (list (list -3 (list "MY_CAE_SEAM_WELD" (cons 1005 pathH))))))
              (princ (strcat (_T "\n[成功] 满焊 " "\n[OK] Seam ") weldType
                             " a=" (rtos leg 2 2) " / s=" (rtos spacing 2 2)
                             (_T " 点数=" " pts=") (itoa (length pathPts))))
            )
            (princ (_T "\n[失败] 无法生成锯齿标记。" "\n[Fail] Zigzag VIS not created."))
          )
        )
        (princ (_T "\n[失败] 轨迹采样点不足。" "\n[Fail] Path sampling too short."))
      )
    )
    (princ (_T "\n[取消] 请只选择一条轨迹。" "\n[Cancel] Select exactly one path."))
  )
  (princ)
)

(defun c:DELSEAMWELD (/ ss i ent ed typ xd app visH hostH oldVis host)
  (unlock-vis-layer)
  (princ (_T "\n请选择【满焊轨迹】或【黄色锯齿符号】: "
             "\nSelect seam path(s) or yellow zigzag symbol(s): "))
  (setq ss (ssget '((0 . "LINE,LWPOLYLINE,ARC,INSERT"))))
  (if ss
    (progn
      (setq i 0)
      (while (< i (sslength ss))
        (setq ent (ssname ss i)
              ed (entget ent '("MY_CAE_SEAM_WELD"))
              typ (cdr (assoc 0 ed))
              xd (assoc -3 ed))
        (if xd
          (progn
            (setq app (cdr (cadr xd)))
            (if (= typ "INSERT")
              (progn
                (setq hostH (cdr (assoc 1005 app)))
                (if (and hostH (setq host (handent hostH)))
                  (progn
                    (entmod (append (entget host) (list (list -3 (list "MY_CAE_SEAM_WELD")))))
                    (entupd host)
                  )
                )
                (entdel ent)
              )
              (progn
                (setq visH (cdr (assoc 1005 app)))
                (if (and visH (setq oldVis (handent visH)))
                  (if (entget oldVis) (entdel oldVis))
                )
                (entmod (append (entget ent) (list (list -3 (list "MY_CAE_SEAM_WELD")))))
                (entupd ent)
              )
            )
          )
        )
        (setq i (1+ i))
      )
      (princ (_T "\n[清除完成] 满焊已删除。" "\n[Done] Seam welds removed."))
    )
  )
  (lock-vis-layer)
  (princ)
)

(defun refresh-seam-welds (/ ss i ent ed xd app weldType leg spacing visH oldVis pathPts newVis newH cnt)
  (setq ss (ssget "_X" '((0 . "LINE,LWPOLYLINE,ARC"))) cnt 0)
  (if ss
    (progn
      (setq i 0)
      (while (< i (sslength ss))
        (setq ent (ssname ss i)
              ed (entget ent '("MY_CAE_SEAM_WELD"))
              xd (assoc -3 ed))
        (if xd
          (progn
            (setq app (cdr (cadr xd))
                  weldType (cdr (nth 0 app))
                  leg (cdr (nth 1 app))
                  spacing (cdr (nth 2 app))
                  visH (cdr (nth 3 app)))
            (if (not leg) (setq leg 4.0))
            (if (not spacing) (setq spacing 5.0))
            (if (and visH (setq oldVis (handent visH)))
              (if (entget oldVis) (entdel oldVis))
            )
            (setq pathPts (cae-entity-path-pts ent spacing)
                  newVis (create-seam-weld-vis pathPts (max 1.2 (* 0.35 leg))))
            (if newVis
              (progn
                (setq newH (cdr (assoc 5 (entget newVis))))
                (attach-seam-weld-xdata ent weldType leg spacing newH)
                (entmod (append (entget newVis)
                                (list (list -3 (list "MY_CAE_SEAM_WELD"
                                  (cons 1005 (cdr (assoc 5 ed))))))))
                (setq cnt (1+ cnt))
              )
            )
          )
        )
        (setq i (1+ i))
      )
    )
  )
  cnt
)

;;; ====================================================================
;;; 梁/杆类型  MY_CAE_MEMBER_KIND（仅 LINE）
;;; 1000 = BEAM | ROD；缺省无 XData = BEAM
;;; 杆：不可分割；仅端点轴向集中力(+拉/-压)；忽略偏置/截面方向/分布载荷
;;; ====================================================================
(defun create-kind-vis (pt kind / r blkName blkRef col lab)
  (cae-vis-unlock)
  (setq r 2.5 col (if (= kind "ROD") 5 3) lab kind) ; ROD=蓝  BEAM=绿
  (setq blkName (cae-make-anon-blk
    (list
      (list '(0 . "CIRCLE") '(8 . "0") (cons 62 col) '(10 0.0 0.0 0.0) (cons 40 r))
      (list '(0 . "TEXT") '(8 . "0") (cons 62 col)
            (cons 10 (list (* r 1.2) (* r 0.2) 0.0)) (cons 40 r) (cons 1 lab))
    )))
  (setq blkRef (entmakex (list '(0 . "INSERT") '(8 . "CAE_VIS_SEC")
                               (cons 2 blkName) (cons 10 pt))))
  (cae-vis-lock)
  blkRef
)

(defun remove-old-kind-visual (ent / ed xd app h old)
  (setq ed (entget ent '("MY_CAE_MEMBER_KIND")))
  (setq xd (assoc -3 ed))
  (if xd
    (progn
      (setq app (cdr (cadr xd)))
      (foreach p app
        (if (= (car p) 1005)
          (if (and (setq old (handent (cdr p))) (entget old))
            (progn (cae-vis-unlock) (entdel old) (cae-vis-lock))
          )
        )
      )
    )
  )
)

(defun cae-set-member-kind (kind / ss i ent ed p1 p2 mid visH nOk)
  (register-all-cae-apps)
  (princ (strcat (_T "\n请选择直线 LINE 标记为 " "\nSelect LINE(s) to mark as ")
                 kind ": "))
  (setq ss (ssget '((0 . "LINE"))))
  (if ss
    (progn
      (setq i 0 nOk 0)
      (cae-vis-begin-batch)
      (while (< i (sslength ss))
        (setq ent (ssname ss i) ed (entget ent))
        ;; 跳过焊缝载体
        (if (assoc -3 (entget ent '("MY_CAE_SEAM_WELD")))
          nil
          (progn
            (setq p1 (cdr (assoc 10 ed)) p2 (cdr (assoc 11 ed))
                  mid (vec-scale (vec-add p1 p2) 0.5))
            (remove-old-kind-visual ent)
            (setq visH (cdr (assoc 5 (entget (create-kind-vis mid kind)))))
            (entmod (append (entget ent)
                            (list (list -3 (list "MY_CAE_MEMBER_KIND"
                              (cons 1000 kind) (cons 1005 visH))))))
            (entupd ent)
            (setq nOk (1+ nOk))
          )
        )
        (setq i (1+ i))
      )
      (cae-vis-end-batch)
      (princ (strcat (_T "\n[成功] " "\n[OK] ") (itoa nOk) " → " kind))
    )
    (princ (_T "\n[取消] 未选中 LINE。" "\n[Cancel] No LINE selected."))
  )
  (princ)
)

(defun c:SETROD ()
  (cae-set-member-kind "ROD")
)

(defun c:SETBEAM ()
  (cae-set-member-kind "BEAM")
)

(defun c:DELKIND (/ ss i ent ed xd app h old)
  (unlock-vis-layer)
  (princ (_T "\n请选择要清除梁/杆类型标记的 LINE: "
             "\nSelect LINE(s) to clear BEAM/ROD kind: "))
  (setq ss (ssget '((0 . "LINE"))))
  (if ss
    (progn
      (setq i 0)
      (while (< i (sslength ss))
        (setq ent (ssname ss i))
        (remove-old-kind-visual ent)
        (entmod (append (entget ent) (list (list -3 (list "MY_CAE_MEMBER_KIND")))))
        (entupd ent)
        (setq i (1+ i))
      )
      (princ (_T "\n[清除完成] 构件类型已恢复为默认梁(BEAM)。"
                 "\n[Done] Kind cleared → default BEAM."))
    )
  )
  (lock-vis-layer)
  (princ)
)

;;; ---------- 启动 ----------
(vl-load-com)
(register-all-cae-apps)
(lock-vis-layer)
(princ (_T "\n[CAE] 梁+杆+板壳+焊缝已加载。默认单位: 线载荷 N-mm、N、MPa；焊点/焊缝 mm。语言: SETLANG"
           "\n[CAE] Beam+Rod+Shell+Weld loaded. Defaults: line load N-mm, N, MPa; welds mm. Lang: SETLANG"))
(princ (_T "\n  类型: SETROD/SETBEAM/DELKIND | 梁载荷: SETLOAD/DELLOAD/SETPTLOAD/DELPTLOAD/SETMOMENT/DELMOMENT"
           "\n  Kind: SETROD/SETBEAM/DELKIND | Beam loads: SETLOAD/DELLOAD/SETPTLOAD/DELPTLOAD/SETMOMENT/DELMOMENT"))
(princ (_T "\n  约束: SETBC/DELBC/ADDBC | 弹簧: SETSPRING/DELSPRING | 截面: SETSEC/DELSEC"
           "\n  BC: SETBC/DELBC/ADDBC | Spring: SETSPRING/DELSPRING | Sec: SETSEC/DELSEC"))
(princ (_T "\n  板壳: SETSHELLLOAD/DELSHELLLOAD | SETSHELLSEC | SETSHELLBC/DELSHELLBC"
           "\n  Shell: SETSHELLLOAD/DELSHELLLOAD | SETSHELLSEC | SETSHELLBC/DELSHELLBC"))
(princ (_T "\n  板壳面: REGION/MESH/SURFACE/EXTRUDEDSURFACE/PLANESURFACE/…/3DFACE"
           "\n  Shell faces: REGION/MESH/SURFACE/EXTRUDEDSURFACE/PLANESURFACE/…/3DFACE"))
(princ (_T "\n  焊缝: SETSPOTWELD/DELSPOTWELD | SETSEAMWELD/DELSEAMWELD | TOGGLEWELD"
           "\n  Weld: SETSPOTWELD/DELSPOTWELD | SETSEAMWELD/DELSEAMWELD | TOGGLEWELD"))
(princ (_T "\n  显示: REFRESH_ALL/SETSCALE/TOGGLELOAD/TOGGLEBC/TOGGLESEC/TOGGLEWELD"
           "\n  Display: REFRESH_ALL/SETSCALE/TOGGLELOAD/TOGGLEBC/TOGGLESEC/TOGGLEWELD"))
(princ)

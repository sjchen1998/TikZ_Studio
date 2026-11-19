;;; ====================================================================
;;; LoadXData.lsp — AutoCAD 梁 + 板壳：截面/属性 / 载荷 / 约束 XData + 可视化
;;; 图层：CAE_VIS_LOAD / CAE_VIS_BC / CAE_VIS_SEC
;;; 语言：*CAE_LANG* ("ZH"|"EN") + SETLANG
;;; 默认单位：分布力 N/mm、集中力 N、面压 MPa；弹性支撑线刚度 N/mm、转动刚度 Nmm/rad
;;; ====================================================================

;;; ---------- 全局显示比例 ----------
(if (not *CAE_SCALE_LOAD*) (setq *CAE_SCALE_LOAD* 1.0))
(if (not *CAE_SCALE_BC*)   (setq *CAE_SCALE_BC*   1.0))
(if (not *CAE_SCALE_SEC*)  (setq *CAE_SCALE_SEC*  1.0))

;;; ---------- 语言：*CAE_LANG* = "ZH" | "EN"；命令 SETLANG 一键切换 ----------
(if (not *CAE_LANG*) (setq *CAE_LANG* "ZH"))

;;; (_T 中文提示 英文提示) — 中文界面仍保留必要英文单位，如 (N/mm)
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

;;; 载荷单位：默认 N/mm、N；可显式选 kN/m、kN
(defun ask-dist-unit (/ u)
  (initget "Nmm kNm")
  (setq u (getkword (_T "\n单位 Nmm=N/mm, kNm=kN/m [Nmm/kNm] <Nmm>: "
                        "\nUnit Nmm=N/mm, kNm=kN/m [Nmm/kNm] <Nmm>: ")))
  (if (not u) (setq u "Nmm"))
  (if (= u "kNm") "kN/m" "N/mm")
)

(defun ask-force-unit (/ u)
  (initget "N kN")
  (setq u (getkword (_T "\n单位 [N/kN] <N>: "
                        "\nUnit [N/kN] <N>: ")))
  (if (not u) (setq u "N"))
  u
)

(defun ask-pressure-unit (/ u)
  (initget "MPa kPa")
  (setq u (getkword (_T "\n单位 [MPa/kPa] <MPa>: "
                        "\nUnit [MPa/kPa] <MPa>: ")))
  (if (not u) (setq u "MPa"))
  u
)

;;; 线刚度默认 N/mm；转动刚度默认 Nmm/rad（菜单用 Nmm-rad/Nm-rad，因 [] 内不能含 /）
(defun ask-trans-k-unit (/ u)
  (initget "Nmm kNm")
  (setq u (getkword (_T "\n单位 [Nmm/kNm] <Nmm>: " "\nUnit [Nmm/kNm] <Nmm>: ")))
  (if (not u) (setq u "Nmm"))
  (if (= u "kNm") "kN/m" "N/mm")
)

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
  (foreach a '("MY_CAE_LOAD" "MY_CAE_POINT_LOAD" "MY_CAE_BC"
               "MY_CAE_COMP_BC" "MY_CAE_SPRING" "MY_CAE_SEC"
               "MY_CAE_SHELL_LOAD" "MY_CAE_SHELL_PROP"
               "MY_CAE_SHELL_GEOM" "MY_CAE_SHELL_BC")
    (cae-regapp a)
  )
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


;;; ---------- 图层（三图层 + 兼容旧 CAE_LOAD_VIS）----------
(defun lock-vis-layer (/ layInfo)
  (setq layInfo '(("CAE_VIS_LOAD" . "1") ("CAE_VIS_BC" . "4") ("CAE_VIS_SEC" . "6")))
  (foreach item layInfo
    (if (not (tblsearch "LAYER" (car item)))
      (command "_.-LAYER" "_N" (car item) "_C" (cdr item) (car item) "")
    )
    (command "_.-LAYER" "_LO" (car item) "")
  )
)
(defun unlock-vis-layer ()
  (foreach lay '("CAE_VIS_LOAD" "CAE_VIS_BC" "CAE_VIS_SEC" "CAE_LOAD_VIS")
    (if (tblsearch "LAYER" lay)
      (command "_.-LAYER" "_U" lay "")
    )
  )
)

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
(defun create-load-block (ent loadMag unitVec unitStr / entData p1 p2 beamVec beamLen arrowLen numArrows i tRatio ptOnBeam ptTail ptTail1 ptTail2 labelPt labelStr blkDefName blkRef)
  (unlock-vis-layer)
  (setq entData (entget ent))
  (setq p1 (cdr (assoc 10 entData)) p2 (cdr (assoc 11 entData)))
  (setq beamVec (vec-sub p2 p1) beamLen (distance p1 p2))
  (setq arrowLen (* beamLen 0.12))
  (if (< arrowLen 100.0) (setq arrowLen 100.0))
  (setq arrowLen (* arrowLen *CAE_SCALE_LOAD*))
  (entmake (list '(0 . "BLOCK") '(2 . "*U") '(70 . 1) '(10 0.0 0.0 0.0)))
  (setq ptTail1 (vec-sub '(0.0 0.0 0.0) (vec-scale unitVec arrowLen)))
  (setq ptTail2 (vec-sub beamVec (vec-scale unitVec arrowLen)))
  (entmake (list '(0 . "LINE") '(8 . "0") (cons 10 ptTail1) (cons 11 ptTail2)))
  (setq numArrows 5 i 0)
  (while (< i numArrows)
    (setq tRatio (/ (float i) (float (1- numArrows))))
    (setq ptOnBeam (vec-scale beamVec tRatio))
    (setq ptTail (vec-sub ptOnBeam (vec-scale unitVec arrowLen)))
    (entmake (list '(0 . "LINE") '(8 . "0") (cons 10 ptTail) (cons 11 ptOnBeam)))
    (entmake (list '(0 . "CIRCLE") '(8 . "0") (cons 10 ptOnBeam) (cons 40 (* arrowLen 0.08))))
    (setq i (1+ i))
  )
  (setq labelPt (vec-sub (vec-scale beamVec 0.5) (vec-scale unitVec (* arrowLen 1.25))))
  (if (or (not unitStr) (= unitStr "")) (setq unitStr "N/mm"))
  (setq labelStr (strcat "q=" (rtos loadMag 2 1) " " unitStr " ("
                         (rtos (car unitVec) 2 2) ","
                         (rtos (cadr unitVec) 2 2) ","
                         (rtos (caddr unitVec) 2 2) ")"))
  (entmake (list '(0 . "TEXT") '(8 . "0") (cons 10 labelPt) (cons 40 (* arrowLen 0.25)) (cons 1 labelStr)))
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

(defun c:SETLOAD (/ ss loadMag unitStr unitVec i beamEnt beamHandle visBlkEnt visHandle)
  (register-all-cae-apps)
  (princ (_T "\n请选择要施加分布载荷的梁直线 (支持框选): "
             "\nSelect beam lines for distributed load (window OK): "))
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
          (setq i 0)
          (while (< i (sslength ss))
            (setq beamEnt (ssname ss i))
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
            (setq i (1+ i))
          )
          (princ (strcat (_T "\n[成功] 已为 " "\n[OK] Wrote distributed load on ")
                         (itoa (sslength ss))
                         (_T " 根梁写入分布载荷 (" " beam(s) (")
                         unitStr
                         (_T ")。" ").")))
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
(defun create-ptload-block (ptNode beamLen forceMag unitVec endTag unitStr / arrowLen ptTail ptConeBase perp1 perp2 pWing1 pWing2 labelPt labelStr blkDefName blkRef)
  (unlock-vis-layer)
  (setq arrowLen (* beamLen 0.18))
  (if (< arrowLen 150.0) (setq arrowLen 150.0))
  (setq arrowLen (* arrowLen *CAE_SCALE_LOAD*))
  (entmake (list '(0 . "BLOCK") '(2 . "*U") '(70 . 1) '(10 0.0 0.0 0.0)))
  (setq ptTail (vec-sub '(0.0 0.0 0.0) (vec-scale unitVec arrowLen)))
  (entmake (list '(0 . "LINE") '(8 . "0") '(62 . 3) (cons 10 ptTail) '(11 0.0 0.0 0.0)))
  (setq ptConeBase (vec-sub '(0.0 0.0 0.0) (vec-scale unitVec (* arrowLen 0.25))))
  (if (< (abs (car unitVec)) 0.9)
    (setq perp1 (vec-unit (list 0.0 (- (caddr unitVec)) (cadr unitVec))))
    (setq perp1 (vec-unit (list (- (caddr unitVec)) 0.0 (car unitVec))))
  )
  (setq perp2 (vec-unit (vec-cross unitVec perp1)))
  (foreach p (list perp1 perp2)
    (setq pWing1 (vec-add ptConeBase (vec-scale p (* arrowLen 0.09))))
    (setq pWing2 (vec-sub ptConeBase (vec-scale p (* arrowLen 0.09))))
    (entmake (list '(0 . "LINE") '(8 . "0") '(62 . 3) (cons 10 pWing1) '(11 0.0 0.0 0.0)))
    (entmake (list '(0 . "LINE") '(8 . "0") '(62 . 3) (cons 10 pWing2) '(11 0.0 0.0 0.0)))
  )
  (setq labelPt (vec-sub '(0.0 0.0 0.0) (vec-scale unitVec (* arrowLen 1.15))))
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

(defun c:SETPTLOAD (/ ent entData beamHandle p1 p2 beamLen endInfo ptNode endTag forceMag unitStr unitVec visBlkEnt visHandle oldXdata oldAppData newRecords i)
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
          (setq forceMag (getreal (strcat (_T "\n[" "\n[") endTag (_T "] 集中力数值 <50.0>: " "] Point force magnitude <50.0>: "))))
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
;;; 简单端点约束  MY_CAE_BC（Mask / Plane / Slide / RotAxis）
;;; ====================================================================
(defun create-bc-block (ptNode beamLen bcMode maskStr e1 e2 e3 endTag / sz pA pB pC pD axEnd labelPt labelStr blkDefName blkRef)
  (unlock-vis-layer)
  (setq sz (* beamLen 0.10))
  (if (< sz 90.0) (setq sz 90.0))
  (setq sz (* sz *CAE_SCALE_BC*))
  (entmake (list '(0 . "BLOCK") '(2 . "*U") '(70 . 1) '(10 0.0 0.0 0.0)))
  (setq pA (list (- sz) (- sz) (- sz)) pB (list sz (- sz) (- sz)))
  (setq pC (list sz sz (- sz)) pD (list (- sz) sz (- sz)))
  (foreach pt (list pA pB pC pD)
    (entmake (list '(0 . "LINE") '(8 . "0") '(62 . 4) '(10 0.0 0.0 0.0) (cons 11 pt)))
  )
  (entmake (list '(0 . "LINE") '(8 . "0") '(62 . 4) (cons 10 pA) (cons 11 pB)))
  (entmake (list '(0 . "LINE") '(8 . "0") '(62 . 4) (cons 10 pB) (cons 11 pC)))
  (entmake (list '(0 . "LINE") '(8 . "0") '(62 . 4) (cons 10 pC) (cons 11 pD)))
  (entmake (list '(0 . "LINE") '(8 . "0") '(62 . 4) (cons 10 pD) (cons 11 pA)))
  (if (/= bcMode "GLOBAL")
    (progn
      (setq axEnd (vec-scale e1 (* sz 1.8)))
      (entmake (list '(0 . "LINE") '(8 . "0") '(62 . 2) '(10 0.0 0.0 0.0) (cons 11 axEnd)))
      (entmake (list '(0 . "CIRCLE") '(8 . "0") '(62 . 2) (cons 10 axEnd) (cons 40 (* sz 0.15))))
    )
  )
  (setq labelPt (list (* sz 1.1) (* sz -1.1) (* sz -1.2)))
  (setq labelStr (strcat "BC[" endTag "]:" bcMode "[" maskStr "]"))
  (entmake (list '(0 . "TEXT") '(8 . "0") '(62 . 4) (cons 10 labelPt) (cons 40 (* sz 0.28)) (cons 1 labelStr)))
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
          (setq bcChoice (getkword (strcat (_T "\n[" "\n[") endTag (_T "] 约束类型 [Mask/Plane/Slide/RotAxis] <Mask>: " "] BC type [Mask/Plane/Slide/RotAxis] <Mask>: "))))
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

;;; 线刚度：折线弹簧 + 引出标注（全局 X/Y/Z）
(defun create-trans-spring-block (ptNode beamLen kx ky kz unitStr endTag /
                                  sz axis perp i t0 t1 pA pB zig amp labelPt labelStr blkDefName blkRef)
  (unlock-vis-layer)
  (setq sz (* beamLen 0.12))
  (if (< sz 100.0) (setq sz 100.0))
  (setq sz (* sz *CAE_SCALE_BC*))
  (setq axis '(0.75 0.55 0.20))
  (if (not (setq axis (vec-unit axis))) (setq axis '(1.0 0.0 0.0)))
  (setq perp (cadr (make-local-basis axis)))
  (setq amp (* sz 0.22))
  (entmake (list '(0 . "BLOCK") '(2 . "*U") '(70 . 1) '(10 0.0 0.0 0.0)))
  ;; 引出短线到弹簧起点
  (entmake (list '(0 . "LINE") '(8 . "0") '(62 . 3)
                 '(10 0.0 0.0 0.0) (cons 11 (vec-scale axis (* sz 0.35)))))
  (setq i 0)
  (while (< i 6)
    (setq t0 (+ 0.35 (* (/ (float i) 6.0) 0.60)))
    (setq t1 (+ 0.35 (* (/ (float (1+ i)) 6.0) 0.60)))
    (setq pA (vec-add (vec-scale axis (* sz t0))
                      (vec-scale perp (if (= (rem i 2) 0) amp (- amp)))))
    (setq pB (vec-add (vec-scale axis (* sz t1))
                      (vec-scale perp (if (= (rem i 2) 0) (- amp) amp))))
    (if (= i 0) (setq pA (vec-scale axis (* sz 0.35))))
    (if (= i 5) (setq pB (vec-scale axis (* sz 0.95))))
    (entmake (list '(0 . "LINE") '(8 . "0") '(62 . 3) (cons 10 pA) (cons 11 pB)))
    (setq i (1+ i))
  )
  ;; 远端支承小横杠
  (setq zig (vec-scale axis (* sz 0.95)))
  (entmake (list '(0 . "LINE") '(8 . "0") '(62 . 3)
                 (cons 10 (vec-add zig (vec-scale perp (* sz 0.18))))
                 (cons 11 (vec-sub zig (vec-scale perp (* sz 0.18))))))
  (setq labelPt (vec-add (vec-scale axis (* sz 1.05)) (vec-scale perp (* sz 0.35))))
  (if (or (not unitStr) (= unitStr "")) (setq unitStr "N/mm"))
  (setq labelStr (strcat "K[" endTag "]="
                         (rtos kx 2 2) "," (rtos ky 2 2) "," (rtos kz 2 2)
                         " " unitStr))
  (entmake (list '(0 . "TEXT") '(8 . "0") '(62 . 3) (cons 10 labelPt)
                 (cons 40 (* sz 0.22)) (cons 1 labelStr)))
  (setq blkDefName (entmake '((0 . "ENDBLK"))))
  (setq blkRef (entmakex (list '(0 . "INSERT") '(8 . "CAE_VIS_BC") (cons 2 blkDefName) (cons 10 ptNode))))
  (lock-vis-layer)
  blkRef
)

;;; 转动/弯曲刚度：平面螺线扭转弹簧 + 引出标注（全局 RX/RY/RZ）
(defun create-rot-spring-block (ptNode beamLen krx kry krz unitStr endTag /
                                sz e1 e2 e3 i ang r p0 p1 lead labelPt labelStr blkDefName blkRef)
  (unlock-vis-layer)
  (setq sz (* beamLen 0.12))
  (if (< sz 100.0) (setq sz 100.0))
  (setq sz (* sz *CAE_SCALE_BC*))
  (setq e1 '(0.20 -0.75 0.55))
  (if (not (setq e1 (vec-unit e1))) (setq e1 '(0.0 1.0 0.0)))
  (setq e3 (make-local-basis e1)
        e2 (cadr e3)
        e3 (caddr e3))
  (entmake (list '(0 . "BLOCK") '(2 . "*U") '(70 . 1) '(10 0.0 0.0 0.0)))
  ;; 引出到螺线中心附近
  (setq lead (vec-scale e1 (* sz 0.40)))
  (entmake (list '(0 . "LINE") '(8 . "0") '(62 . 6)
                 '(10 0.0 0.0 0.0) (cons 11 lead)))
  (setq i 0 p0 nil)
  (while (<= i 24)
    (setq ang (* (/ (float i) 24.0) (* 2.5 pi)))
    (setq r (* sz (+ 0.12 (* (/ (float i) 24.0) 0.28))))
    (setq p1 (vec-add lead
                      (vec-add (vec-scale e2 (* r (cos ang)))
                               (vec-scale e3 (* r (sin ang))))))
    (if p0
      (entmake (list '(0 . "LINE") '(8 . "0") '(62 . 6) (cons 10 p0) (cons 11 p1)))
    )
    (setq p0 p1 i (1+ i))
  )
  (entmake (list '(0 . "CIRCLE") '(8 . "0") '(62 . 6) (cons 10 p0) (cons 40 (* sz 0.05))))
  (setq labelPt (vec-add lead (vec-scale e2 (* sz 0.55))))
  (if (or (not unitStr) (= unitStr "")) (setq unitStr "Nmm/rad"))
  (setq labelStr (strcat "KR[" endTag "]="
                         (rtos krx 2 2) "," (rtos kry 2 2) "," (rtos krz 2 2)
                         " " unitStr))
  (entmake (list '(0 . "TEXT") '(8 . "0") '(62 . 6) (cons 10 labelPt)
                 (cons 40 (* sz 0.22)) (cons 1 labelStr)))
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

(defun create-comp-bc-block (ptNode beamLen uVecs rVecs uMask rMask endTag / sz pA pB pC pD axEnd labelPt labelStr blkDefName blkRef)
  (unlock-vis-layer)
  (setq sz (* beamLen 0.10))
  (if (< sz 90.0) (setq sz 90.0))
  (setq sz (* sz *CAE_SCALE_BC*))
  (entmake (list '(0 . "BLOCK") '(2 . "*U") '(70 . 1) '(10 0.0 0.0 0.0)))
  (setq pA (list (- sz) (- sz) (- sz)) pB (list sz (- sz) (- sz)))
  (setq pC (list sz sz (- sz)) pD (list (- sz) sz (- sz)))
  (foreach pt (list pA pB pC pD)
    (entmake (list '(0 . "LINE") '(8 . "0") '(62 . 4) '(10 0.0 0.0 0.0) (cons 11 pt)))
  )
  (entmake (list '(0 . "LINE") '(8 . "0") '(62 . 4) (cons 10 pA) (cons 11 pB)))
  (entmake (list '(0 . "LINE") '(8 . "0") '(62 . 4) (cons 10 pB) (cons 11 pC)))
  (entmake (list '(0 . "LINE") '(8 . "0") '(62 . 4) (cons 10 pC) (cons 11 pD)))
  (entmake (list '(0 . "LINE") '(8 . "0") '(62 . 4) (cons 10 pD) (cons 11 pA)))
  (foreach u uVecs
    (setq axEnd (vec-scale u (* sz 1.8)))
    (entmake (list '(0 . "LINE") '(8 . "0") '(62 . 6) '(10 0.0 0.0 0.0) (cons 11 axEnd)))
  )
  (foreach r rVecs
    (setq axEnd (vec-scale r (* sz 2.1)))
    (entmake (list '(0 . "LINE") '(8 . "0") '(62 . 2) '(10 0.0 0.0 0.0) (cons 11 axEnd)))
    (entmake (list '(0 . "CIRCLE") '(8 . "0") '(62 . 2) (cons 10 axEnd) (cons 40 (* sz 0.16))))
  )
  (setq labelPt (list (* sz 1.1) (* sz -1.1) (* sz -1.2)))
  (setq labelStr (strcat "BC[" endTag "] U:" uMask " R:" rMask))
  (entmake (list '(0 . "TEXT") '(8 . "0") '(62 . 4) (cons 10 labelPt) (cons 40 (* sz 0.28)) (cons 1 labelStr)))
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
          (setq addType (getkword (strcat (_T "\n[" "\n[") endTag "] U:" (itoa (length uVecs))
                                          " R:" (itoa (length rVecs))
                                          (_T " 叠加 Plane/Slide/RotAxis/FixAll [Plane/Slide/RotAxis/FixAll] <Plane>: "
                                              " Add [Plane/Slide/RotAxis/FixAll] <Plane>: "))))
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
  (unlock-vis-layer)
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
  (lock-vis-layer)
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
              (progn (unlock-vis-layer) (entdel oldBlk) (lock-vis-layer))
            )
          )
        )
      )
    )
  )
)

(defun c:SETSEC (/ ss typeChoice secType secSpec matChoice matName dirPt offPt offDist i beamEnt beamHandle entData p1 p2 ex vy vz offUnit offsetVec visBlkEnt visHandle validCount)
  (register-all-cae-apps)
  (princ (_T "\n请选择梁直线 (支持框选): " "\nSelect beam lines (window OK): "))
  (setq ss (ssget '((0 . "LINE"))))
  (if ss
    (progn
      (initget "Angle Channel IBeam Pipe RectTube Circle Rect Custom")
      (setq typeChoice (getkword (_T "\n截面类型 [Angle/Channel/IBeam/Pipe/RectTube/Circle/Rect/Custom] <IBeam>: "
                                "\nSection type [Angle/Channel/IBeam/Pipe/RectTube/Circle/Rect/Custom] <IBeam>: ")))
      (if (not typeChoice) (setq typeChoice "IBeam"))
      (setq secType typeChoice)
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
      (setq dirPt (getpoint (_T "\n[姿态] 不在梁上的一点 → 截面 Y 轴: "
                           "\n[Orientation] Point off beam → section Y axis: ")))
      (if dirPt
        (progn
          (setq dirPt (trans dirPt 1 0))
          (setq offPt (getpoint (_T "\n[偏置] 不在梁上的一点 → 偏置方向: "
                           "\n[Offset] Point off beam → offset direction: ")))
          (if offPt
            (progn
              (setq offPt (trans offPt 1 0))
              (setq offDist (getreal (_T "\n偏置距离 (mm，0=无偏置) <0.0>: " "\nOffset distance (mm, 0=none) <0.0>: ")))
              (if (not offDist) (setq offDist 0.0))
              (setq i 0 validCount 0)
              (while (< i (sslength ss))
                (setq beamEnt (ssname ss i))
                (setq entData (entget beamEnt))
                (setq beamHandle (cdr (assoc 5 entData)))
                (setq p1 (cdr (assoc 10 entData)) p2 (cdr (assoc 11 entData)))
                (setq ex (vec-unit (vec-sub p2 p1)))
                (setq vy (get-perp-unit-vec p1 p2 dirPt))
                (setq offUnit (get-perp-unit-vec p1 p2 offPt))
                (if (and ex vy offUnit)
                  (progn
                    (setq vz (vec-unit (vec-cross ex vy)))
                    (setq offsetVec (vec-scale offUnit offDist))
                    (remove-old-sec-visual beamEnt)
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
              (princ (strcat (_T "\n[成功] " "\n[OK] ") (itoa validCount) (_T " 根梁 [" " beam(s) [") secType ":" secSpec "] / " matName))
            )
            (princ (_T "\n[取消] 未指定偏置点。" "\n[Cancel] Offset point not specified."))
          )
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
            (if (or (not unitStr) (/= (type unitStr) 'STR)) (setq unitStr "N/mm"))
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
    )
  )
  count
)

;;; ---------- 板壳刷新（与梁共用 *CAE_SCALE_* 与 CAE_VIS_* 图层）----------
(defun refresh-shell-loads (/ ss i ent entHandle entData xdata appData idx newRecs
                             loadType lc mag unitStr unitVec numPts headLen pts j
                             info cenPt diagLen loadTypeTag visBlk visHandle count)
  (vl-load-com)
  (setq count 0
        ss (ssget "_X" '((0 . "MESH,REGION,SURFACE,3DSOLID,3DFACE,LWPOLYLINE")
                         (-3 ("MY_CAE_SHELL_LOAD")))))
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
                        unitVec (cdr (nth (+ idx 4) appData))
                        numPts (cdr (nth (+ idx 6) appData))
                        headLen 7)
                )
                (progn
                  (setq unitVec (cdr (nth (+ idx 3) appData))
                        numPts (cdr (nth (+ idx 5) appData))
                        headLen 6
                        unitStr (cond
                                  ((= loadType "EDGE_LOAD") "N/mm")
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
                 (if (and unitVec cenPt)
                   (progn
                     (setq visBlk (create-shell-faceload-block cenPt diagLen loadTypeTag mag unitVec unitStr))
                     (setq visHandle (cdr (assoc 5 (entget visBlk))))
                     (entmod (append (entget visBlk)
                                     (list (list -3 (list "MY_CAE_SHELL_LOAD" (cons 1005 entHandle))))))
                     (setq newRecs (append newRecs
                       (list (cons 1000 loadType) (cons 1000 lc) (cons 1040 mag)
                             (cons 1000 unitStr) (cons 1013 unitVec)
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
        ss (ssget "_X" '((0 . "MESH,REGION,SURFACE,3DSOLID,3DFACE,LWPOLYLINE")
                         (-3 ("MY_CAE_SHELL_BC")))))
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
        ss (ssget "_X" '((0 . "MESH,REGION,SURFACE,3DSOLID,3DFACE,LWPOLYLINE")
                         (-3 ("MY_CAE_SHELL_PROP")))))
  (if ss
    (progn
      (setq i 0)
      (while (< i (sslength ss))
        (setq ent (ssname ss i)
              entData (entget ent '("MY_CAE_SHELL_PROP"))
              entHandle (cdr (assoc 5 entData))
              xdata (assoc -3 entData))
        (if xdata
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
        (setq i (1+ i))
      )
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
                 (if (or (not unitStr) (/= (type unitStr) 'STR)) (setq unitStr "N/mm"))
                 (setq visBlkEnt (create-trans-spring-block ptNode beamLen k1 k2 k3 unitStr endTag))
                )
                ((= kindTag "ROT")
                 (if (or (not unitStr) (/= (type unitStr) 'STR)) (setq unitStr "Nmm/rad"))
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

(defun c:REFRESH_ALL (/ ssOld i cDist cPt cBc cComp cSec cSpring cShLoad cShBc cShProp)
  (vl-load-com)
  (unlock-vis-layer)
  (setq ssOld (ssget "_X" '((8 . "CAE_VIS_LOAD,CAE_VIS_BC,CAE_VIS_SEC,CAE_LOAD_VIS"))))
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
        cBc     (refresh-simple-bcs)
        cComp   (refresh-comp-bcs)
        cSpring (refresh-springs)
        cSec    (refresh-sections)
        cShLoad (refresh-shell-loads)
        cShBc   (refresh-shell-bcs)
        cShProp (refresh-shell-props))
  (lock-vis-layer)
  (princ (strcat (_T "\n[刷新] 梁截面=" "\n[Refresh] BeamSec=") (itoa cSec)
                 (_T " 分布=" " Dist=") (itoa cDist)
                 (_T " 集中=" " Point=") (itoa cPt)
                 (_T " 约束=" " BC=") (itoa cBc)
                 (_T " 复合=" " Comp=") (itoa cComp)
                 (_T " 弹簧=" " Spring=") (itoa cSpring)))
  (princ (strcat (_T "\n       板壳属性=" "\n       ShellProp=") (itoa cShProp)
                 (_T " 板壳载荷=" " ShellLoad=") (itoa cShLoad)
                 (_T " 板壳约束=" " ShellBC=") (itoa cShBc)))
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

;;; ---------- 图层显隐（梁与板壳共用 CAE_VIS_*）----------
(defun toggle-cae-layer (layName cnLabel / layData colVal)
  (setq layData (tblsearch "LAYER" layName))
  (if layData
    (progn
      (setq colVal (cdr (assoc 62 layData)))
      (if (< colVal 0)
        (progn (command "_.-LAYER" "_ON" layName "")
               (princ (strcat (_T "\n[显示] " "\n[ON] ") cnLabel)))
        (progn (command "_.-LAYER" "_OFF" layName "")
               (princ (strcat (_T "\n[隐藏] " "\n[OFF] ") cnLabel)))
      )
    )
    (princ (strcat (_T "\n[提示] 图层 " "\n[Hint] Layer ") layName (_T " 尚未创建。" " not created yet.")))
  )
  (princ)
)
(defun c:TOGGLESEC () (toggle-cae-layer "CAE_VIS_SEC" (_T "截面/板壳属性" "Section/ShellProp")))
(defun c:TOGGLELOAD () (toggle-cae-layer "CAE_VIS_LOAD" (_T "载荷(梁+板壳)" "Load (beam+shell)")))
(defun c:TOGGLEBC () (toggle-cae-layer "CAE_VIS_BC" (_T "约束(梁+板壳)" "BC (beam+shell)")))

;;; ====================================================================
;;; 板壳：几何 / 边面载荷 / 属性 / 复合约束
;;; ====================================================================

(defun get-shell-center-normal (ent / ed eType obj normWCS minPt maxPt cenPt diagLen verts v1 v2 i beforeEnt tempClone ssTmp subEnt pts)
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
    ;; 情况 A：REGION 自带 ActiveX Normal 属性，直接读取！
    ((and (= eType "REGION") (vlax-property-available-p obj 'Normal))
     (setq normWCS (vec-unit (vlax-safearray->list (vlax-variant-value (vla-get-Normal obj)))))
    )
    ;; 情况 B：LWPOLYLINE / CIRCLE / ARC 自带组码 210
    ((assoc 210 ed)
     (setq normWCS (vec-unit (cdr (assoc 210 ed))))
    )
    ;; 情况 C：MESH -> 直接提取组码 10 顶点列表，找 3 个不共线顶点做叉乘
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
    ;; 情况 D：3DFACE -> 直接用组码 10, 11, 12 叉乘
    ((= eType "3DFACE")
     (setq v1 (vec-sub (cdr (assoc 11 ed)) (cdr (assoc 10 ed))))
     (setq v2 (vec-sub (cdr (assoc 12 ed)) (cdr (assoc 10 ed))))
     (setq normWCS (vec-unit (vec-cross v1 v2)))
    )
  )
  
  ;; 兜底（如复杂 SURFACE）：克隆炸开一次取任意两段边向量叉乘
  (if (not normWCS)
    (progn
      (setq beforeEnt (entlast))
      (command "_.COPY" ent "" '(0.0 0.0 0.0) '(0.0 0.0 0.0))
      (setq tempClone (entlast))
      (if (not (equal beforeEnt tempClone))
        (progn
          (command "_.EXPLODE" tempClone)
          (setq ssTmp (ssadd) subEnt (entnext beforeEnt) pts nil)
          (while subEnt
            (ssadd subEnt ssTmp)
            (if (vlax-curve-isPlanar subEnt)
              (setq pts (append pts (list (vlax-curve-getStartPoint subEnt) (vlax-curve-getEndPoint subEnt))))
            )
            (setq subEnt (entnext subEnt))
          )
          (if (>= (length pts) 3)
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
          (if (> (sslength ssTmp) 0) (command "_.ERASE" ssTmp ""))
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
(defun create-shell-edgeload-block (ptsList loadMag unitVec unitStr / pOrigin totalLen i arrowLen locPts pEndRel ptOnEdge ptTail prevTail labelPt labelStr blkDefName blkRef)
  (unlock-vis-layer)
  (setq pOrigin (car ptsList))
  (setq totalLen 0.0 i 0)
  (while (< i (1- (length ptsList)))
    (setq totalLen (+ totalLen (distance (nth i ptsList) (nth (1+ i) ptsList))))
    (setq i (1+ i))
  )
  
  (setq arrowLen (* (max (* totalLen 0.14) 80.0) *CAE_SCALE_LOAD*))
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
    (setq ptTail (vec-sub ptOnEdge (vec-scale unitVec arrowLen)))
    (entmake (list '(0 . "LINE") '(8 . "0") '(62 . 1) (cons 10 ptTail) (cons 11 ptOnEdge)))
    (entmake (list '(0 . "CIRCLE") '(8 . "0") '(62 . 1) (cons 10 ptOnEdge) (cons 40 (* arrowLen 0.08))))
    (if prevTail
      (entmake (list '(0 . "LINE") '(8 . "0") '(62 . 1) (cons 10 prevTail) (cons 11 ptTail)))
    )
    (setq prevTail ptTail)
  )
  
  (setq labelPt (vec-sub (nth (/ (length locPts) 2) locPts) (vec-scale unitVec (* arrowLen 1.25))))
  (if (or (not unitStr) (= unitStr "")) (setq unitStr "N/mm"))
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
  
  ;; 1. 绘制从尾部指向面几何中心 (0,0,0) 的主箭杆（橙红色=30）
  (setq ptTail (vec-sub '(0.0 0.0 0.0) (vec-scale unitVec arrowLen)))
  (entmake (list '(0 . "LINE") '(8 . "0") '(62 . 30) (cons 10 ptTail) '(11 0.0 0.0 0.0)))
  
  ;; 2. 绘制三维正交双翼箭头尖端（任意三维视角均清晰立体）
  (setq ptConeBase (vec-sub '(0.0 0.0 0.0) (vec-scale unitVec (* arrowLen 0.25))))
  (setq perp1 (cadr (make-local-basis unitVec)))
  (setq perp2 (vec-unit (vec-cross unitVec perp1)))
  
  (foreach p (list perp1 perp2)
    (setq pWing1 (vec-add ptConeBase (vec-scale p (* arrowLen 0.10))))
    (setq pWing2 (vec-sub ptConeBase (vec-scale p (* arrowLen 0.10))))
    (entmake (list '(0 . "LINE") '(8 . "0") '(62 . 30) (cons 10 pWing1) '(11 0.0 0.0 0.0)))
    (entmake (list '(0 . "LINE") '(8 . "0") '(62 . 30) (cons 10 pWing2) '(11 0.0 0.0 0.0)))
  )
  
  ;; 在作用中心画一个定位圆环标记
  (entmake (list '(0 . "CIRCLE") '(8 . "0") '(62 . 30) '(10 0.0 0.0 0.0) (cons 40 (* arrowLen 0.08))))
  
  ;; 3. 根据是【面压强】还是【面总载荷】生成对应物理标签
  (setq labelPt (vec-sub '(0.0 0.0 0.0) (vec-scale unitVec (* arrowLen 1.15))))
  (if (or (not unitStr) (= unitStr ""))
    (setq unitStr (if (= loadTypeTag "TOTAL") "N" "MPa"))
  )
  (setq labelStr (if (= loadTypeTag "TOTAL")
                   (strcat "F_total=" (rtos valMag 2 2) " " unitStr " (" (rtos (car unitVec) 2 2) "," (rtos (cadr unitVec) 2 2) "," (rtos (caddr unitVec) 2 2) ")")
                   (strcat "P_face=" (rtos valMag 2 3) " " unitStr " (" (rtos (car unitVec) 2 2) "," (rtos (cadr unitVec) 2 2) "," (rtos (caddr unitVec) 2 2) ")")))
  (entmake (list '(0 . "TEXT") '(8 . "0") '(62 . 30) (cons 10 labelPt) (cons 40 (* arrowLen 0.22)) (cons 1 labelStr)))
  
  (setq blkDefName (entmake '((0 . "ENDBLK"))))
  (setq blkRef (entmakex (list '(0 . "INSERT") '(8 . "CAE_VIS_LOAD") (cons 2 blkDefName) (cons 10 cenPt))))
  (lock-vis-layer)
  blkRef
)


;;; ====================================================================
;;; 三维板壳加载模块（第二部分：规范化关键字交互命令 SETSHELLLOAD / DELSHELLLOAD）
;;; ====================================================================

(defun c:SETSHELLLOAD (/ selMain mainEnt mainType mainHandle loadScope edgeMode p1 pMid p2 pts loadMag unitStr vecInput unitVec shellInfo cenPt normVec diagLen pressType subType valMode loadTypeTag visBlk visHandle oldXd newRecs ptPairs)
  (vl-load-com)
  (register-shell-load-app)
  
  (setq selMain (entsel (_T "\n[第1步] 请选择目标板壳面片 (MESH / REGION / SURFACE / 3DFACE): "
                             "\n[Step 1] Select shell face (MESH / REGION / SURFACE / 3DFACE): ")))
  (if selMain
    (progn
      (setq mainEnt (car selMain))
      (setq mainType (cdr (assoc 0 (entget mainEnt))))
      (setq mainHandle (cdr (assoc 5 (entget mainEnt))))
      
      (if (member mainType '("MESH" "REGION" "SURFACE" "3DSOLID" "3DFACE" "LWPOLYLINE"))
        (progn
          (initget "Edge Face")
          (setq loadScope (getkword (_T "\n[第2步] 加载位置 Edge=边线载荷, Face=面压强/面力 [Edge/Face] <Edge>: "
                                 "\n[Step 2] Location Edge=edge load, Face=face pressure/force [Edge/Face] <Edge>: ")))
          (if (not loadScope) (setq loadScope "Edge"))
          
          (cond
            ;; 分支 A：边分布线载荷
            ((= loadScope "Edge")
             (initget "Line Arc")
             (setq edgeMode (getkword (_T "\n加载边界形态 Line=直边两点, Arc=三点圆弧 [Line/Arc] <Line>: "
                                "\nEdge shape Line=2 pts, Arc=3 pts [Line/Arc] <Line>: ")))
             (if (not edgeMode) (setq edgeMode "Line"))
             
             (if (= edgeMode "Line")
               (progn
                 (setq p1 (getpoint (_T "\n请捕捉加载边界的【起点】: " "\nPick edge [start] point: ")))
                 (if p1 (setq p2 (getpoint p1 (_T "\n请捕捉加载边界的【终点】: " "\nPick edge [end] point: "))))
                 (if (and p1 p2) (setq pts (list (trans p1 1 0) (trans p2 1 0))))
               )
               (progn
                 (setq p1 (getpoint (_T "\n请捕捉圆弧边界的【起点】: " "\nPick arc [start]: ")))
                 (if p1 (setq pMid (getpoint p1 (_T "\n请捕捉圆弧边界的【弧上中间点】: " "\nPick arc [mid]: "))))
                 (if pMid (setq p2 (getpoint pMid (_T "\n请捕捉圆弧边界的【终点】: " "\nPick arc [end]: "))))
                 (if (and p1 pMid p2)
                   (setq pts (sample-3pt-arc-3d (trans p1 1 0) (trans pMid 1 0) (trans p2 1 0) 12))
                 )
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
               (setq unitVec (if (< loadMag 0.0) (vec-scale normVec -1.0) normVec))
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
             
             (if unitVec
               (progn
                 (setq visBlk (create-shell-faceload-block cenPt diagLen loadTypeTag loadMag unitVec unitStr))
                 (setq visHandle (cdr (assoc 5 (entget visBlk))))
                 
                 (setq oldXd (cdr (cadr (assoc -3 (entget mainEnt '("MY_CAE_SHELL_LOAD"))))))
                 (setq newRecs (append oldXd
                   (list (cons 1000 subType)
                         (cons 1000 "LC1")
                         (cons 1040 loadMag)
                         (cons 1000 unitStr)
                         (cons 1013 unitVec)
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
  (setq ss (ssget '((0 . "MESH,REGION,SURFACE,3DSOLID,3DFACE,LWPOLYLINE,INSERT"))))
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

;;; 提取 REGION 的闭合边界环三维点列（区分外环 OUTER 与内孔 INNER）
(defun extract-region-loops-3d (ent / eType oldUcs beforeEnt tempClone ssTmp subEnt curves segPts loops curLoop foundNext pEnd ptS ptE maxDiag maxIdx i diag minP maxP resList pMid)
  (setq eType (cdr (assoc 0 (entget ent))))
  (if (= eType "MESH")
    (list (cons 1000 "V1_NATIVE_MESH"))
    (progn
      (setq oldUcs (getvar "WORLDUCS"))
      (if (= oldUcs 0) (command "_.UCS" "_W"))
      
      (setq beforeEnt (entlast))
      (command "_.COPY" ent "" '(0.0 0.0 0.0) '(0.0 0.0 0.0))
      (setq tempClone (entlast))
      (setq curves nil ssTmp (ssadd))
      
      (if (not (equal beforeEnt tempClone))
        (progn
          (if (/= eType "3DFACE") (command "_.EXPLODE" tempClone))
          (setq subEnt (entnext beforeEnt))
          (while subEnt
            (ssadd subEnt ssTmp)
            (if (member (cdr (assoc 0 (entget subEnt))) '("LINE" "ARC" "CIRCLE" "SPLINE" "ELLIPSE"))
              (progn
                (if (= (cdr (assoc 0 (entget subEnt))) "LINE")
                  (setq segPts (list (vlax-curve-getStartPoint subEnt)
                                     (vlax-curve-getEndPoint subEnt)))
                  (progn
                    (setq pMid (vlax-curve-getPointAtParam subEnt
                                 (* 0.5 (+ (vlax-curve-getStartParam subEnt)
                                           (vlax-curve-getEndParam subEnt)))))
                    (setq segPts (sample-3pt-arc-3d (vlax-curve-getStartPoint subEnt)
                                                    pMid
                                                    (vlax-curve-getEndPoint subEnt) 16))
                  )
                )
                (setq curves (append curves (list segPts)))
              )
            )
            (setq subEnt (entnext subEnt))
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
              (setq curves (append (subseq curves 0 i) (subseq curves (1+ i))))
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
  (unlock-all-cae-layers)
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
  (lock-all-cae-layers)
  blkRef
)

;;; ====================================================================
;;; 板壳属性与约束模块 - 代码块 2/3：SETSHELL 命令与约束符号块
;;; ====================================================================

;;; 命令：SETSHELL - 批量设置板壳单元类型、厚度、偏置与材料
(defun c:SETSHELL (/ ss thChoice theoryType thick offChoice offZ matChoice matName i ent entHandle info cenPt normVec diagLen oldXd oldBlk visBlk visHandle geomRecords)
  (vl-load-com)
  (register-shell-prop-app)
  (princ (_T "\n请选择要设置属性的板壳面片 (MESH / REGION / SURFACE / 3DFACE，支持框选): "
         "\nSelect shell faces for properties (MESH / REGION / SURFACE / 3DFACE, window OK): "))
  (setq ss (ssget '((0 . "MESH,REGION,SURFACE,3DSOLID,3DFACE,LWPOLYLINE"))))
  
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
      
      (initget "Q235B Q355B 45Steel Al6061 Concrete Other")
      (setq matChoice (getkword (_T "\n材料牌号 Other=自定义 [Q235B/Q355B/45Steel/Al6061/Concrete/Other] <Q355B>: "
                                "\nMaterial [Q235B/Q355B/45Steel/Al6061/Concrete/Other] <Q355B>: ")))
      (if (not matChoice) (setq matChoice "Q355B"))
      (if (= matChoice "Other")
        (progn (setq matName (getstring T (_T "\n自定义材料名称: " "\nCustom material name: "))) (if (= matName "") (setq matName "Custom_Mat")))
        (setq matName matChoice)
      )
      
      (setq i 0)
      (while (< i (sslength ss))
        (setq ent (ssname ss i))
        (setq entHandle (cdr (assoc 5 (entget ent))))
        (setq info (get-shell-center-normal ent))
        (setq cenPt (car info) normVec (cadr info) diagLen (caddr info))
        
        (setq oldXd (assoc -3 (entget ent '("MY_CAE_SHELL_PROP"))))
        (if oldXd
          (if (setq oldBlk (handent (cdr (nth 4 (cdr (cadr oldXd))))))
            (if (entget oldBlk) (progn (unlock-all-cae-layers) (entdel oldBlk) (lock-all-cae-layers)))
          )
        )
        
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
        (setq i (1+ i))
      )
      (princ (strcat (_T "\n[成功] 已为 " "\n[OK] Set properties on ") (itoa (sslength ss))
                 (_T " 块板壳设置属性 [" " shell(s) [") theoryType ", t=" (rtos thick 2 1) "mm, " matName "]"))
    )
  )
  (princ)
)

;;; 绘制板壳边约束或面约束整体符号 -> 放入 CAE_VIS_BC (青色=4)
(defun create-shell-bc-block (ptsList bcScope uVecs rVecs uMask rMask / pOrigin totalLen i sz locPts pt blkDefName blkRef labelPt labelStr)
  (unlock-all-cae-layers)
  (setq pOrigin (car ptsList))
  (if (= bcScope "FACE_BC")
    (setq sz (* 120.0 *CAE_SCALE_BC*))
    (progn
      (setq totalLen 0.0 i 0)
      (while (< i (1- (length ptsList)))
        (setq totalLen (+ totalLen (distance (nth i ptsList) (nth (1+ i) ptsList))))
        (setq i (1+ i))
      )
      (setq sz (* (max (* totalLen 0.08) 60.0) *CAE_SCALE_BC*))
    )
  )
  
  (entmake (list '(0 . "BLOCK") '(2 . "*U") '(70 . 1) '(10 0.0 0.0 0.0)))
  
  (if (= (length ptsList) 2)
    (setq locPts (list '(0.0 0.0 0.0)
                       (vec-scale (vec-sub (cadr ptsList) pOrigin) 0.5)
                       (vec-sub (cadr ptsList) pOrigin)))
    (setq locPts (mapcar '(lambda (p) (vec-sub p pOrigin)) ptsList))
  )
  
  (foreach pt locPts
    (entmake (list '(0 . "CIRCLE") '(8 . "0") '(62 . 4) (cons 10 pt) (cons 40 (* sz 0.14))))
  )
  (if (> (length locPts) 1)
    (progn
      (setq i 0)
      (while (< i (1- (length locPts)))
        (entmake (list '(0 . "LINE") '(8 . "0") '(62 . 4) (cons 10 (nth i locPts)) (cons 11 (nth (1+ i) locPts))))
        (setq i (1+ i))
      )
    )
  )
  
  (foreach u uVecs
    (entmake (list '(0 . "LINE") '(8 . "0") '(62 . 6) '(10 0.0 0.0 0.0) (cons 11 (vec-scale u (* sz 1.5)))))
  )
  (foreach r rVecs
    (entmake (list '(0 . "LINE") '(8 . "0") '(62 . 2) '(10 0.0 0.0 0.0) (cons 11 (vec-scale r (* sz 1.8)))))
  )
  
  (setq labelPt (nth (/ (length locPts) 2) locPts))
  (setq labelStr (strcat bcScope " U:" uMask " R:" rMask))
  (entmake (list '(0 . "TEXT") '(8 . "0") '(62 . 4) (cons 10 labelPt) (cons 40 (* sz 0.25)) (cons 1 labelStr)))
  
  (setq blkDefName (entmake '((0 . "ENDBLK"))))
  (setq blkRef (entmakex (list '(0 . "INSERT") '(8 . "CAE_VIS_BC") (cons 2 blkDefName) (cons 10 pOrigin))))
  (lock-all-cae-layers)
  blkRef
)

;;; ====================================================================
;;; 板壳属性与约束模块 - 代码块 3/3：ADDSHELLBC 与 DELSHELLBC 命令
;;; ====================================================================

;;; 命令：ADDSHELLBC - 对板壳边界线或整个面施加复合约束（杜绝单点应力奇异）
(defun c:ADDSHELLBC (/ selMain mainEnt mainType mainHandle bcScope edgeMode p1 pMid p2 pts shellInfo bcType pA pB v1 v2 nVec sVec rAxis uVecs rVecs uTriad rTriad scopeTag visPts visBlk visHandle oldXd newRecs ptPairs)
  (vl-load-com)
  (register-shell-bc-app)
  
  (setq selMain (entsel (_T "\n[第1步] 请选择要施加约束的板壳面片 (MESH / REGION / SURFACE / 3DFACE): "
                             "\n[Step 1] Select shell face for BC (MESH / REGION / SURFACE / 3DFACE): ")))
  (if selMain
    (progn
      (setq mainEnt (car selMain))
      (setq mainType (cdr (assoc 0 (entget mainEnt))))
      (setq mainHandle (cdr (assoc 5 (entget mainEnt))))
      
      (if (member mainType '("MESH" "REGION" "SURFACE" "3DSOLID" "3DFACE" "LWPOLYLINE"))
        (progn
          (initget "Edge Face")
          (setq bcScope (getkword (_T "\n[第2步] 约束区域 Edge=边界线, Face=整面 [Edge/Face] <Edge>: "
                               "\n[Step 2] BC region Edge/Face [Edge/Face] <Edge>: ")))
          (if (not bcScope) (setq bcScope "Edge"))
          
          (if (= bcScope "Edge")
            (progn
              (initget "Line Arc")
              (setq edgeMode (getkword (_T "\n约束边界形态 Line=直边两点, Arc=三点圆弧 [Line/Arc] <Line>: "
                                "\nBC edge shape Line/Arc [Line/Arc] <Line>: ")))
              (if (not edgeMode) (setq edgeMode "Line"))
              (if (= edgeMode "Line")
                (progn
                  (setq p1 (getpoint (_T "\n请捕捉约束边界的【起点】: " "\nPick BC edge [start]: ")))
                  (if p1 (setq p2 (getpoint p1 (_T "\n请捕捉约束边界的【终点】: " "\nPick BC edge [end]: "))))
                  (if (and p1 p2) (setq pts (list (trans p1 1 0) (trans p2 1 0))))
                )
                (progn
                  (setq p1 (getpoint (_T "\n请捕捉圆弧约束边界的【起点】: " "\nPick BC arc [start]: ")))
                  (if p1 (setq pMid (getpoint p1 (_T "\n请捕捉圆弧约束边界的【弧上中间点】: " "\nPick BC arc [mid]: "))))
                  (if pMid (setq p2 (getpoint pMid (_T "\n请捕捉圆弧约束边界的【终点】: " "\nPick BC arc [end]: "))))
                  (if (and p1 pMid p2)
                    (setq pts (sample-3pt-arc-3d (trans p1 1 0) (trans pMid 1 0) (trans p2 1 0) 12))
                  )
                )
              )
            )
            (progn
              (setq shellInfo (get-shell-center-normal mainEnt))
              (setq pts (list (car shellInfo)))
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
              (setq scopeTag (if (= bcScope "Edge") "EDGE_BC" "FACE_BC"))
              (setq visPts (if (= bcScope "Edge") pts nil))
              
              (setq visBlk (create-shell-bc-block pts scopeTag uVecs rVecs (nth 3 uTriad) (nth 3 rTriad)))
              (setq visHandle (cdr (assoc 5 (entget visBlk))))
              
              (setq ptPairs (if visPts (mapcar '(lambda (p) (cons 1010 p)) visPts) nil))
              (setq oldXd (cdr (cadr (assoc -3 (entget mainEnt '("MY_CAE_SHELL_BC"))))))
              (setq newRecs (append oldXd
                (list (cons 1000 scopeTag)
                      (cons 1000 (nth 3 uTriad)) (cons 1013 (nth 0 uTriad)) (cons 1013 (nth 1 uTriad)) (cons 1013 (nth 2 uTriad))
                      (cons 1000 (nth 3 rTriad)) (cons 1013 (nth 0 rTriad)) (cons 1013 (nth 1 rTriad)) (cons 1013 (nth 2 rTriad))
                      (cons 1005 visHandle)
                      (cons 1070 (length visPts)))
                ptPairs))
              
              (entmod (append (entget mainEnt) (list (list -3 (cons "MY_CAE_SHELL_BC" newRecs)))))
              (entupd mainEnt)
              (entmod (append (entget visBlk) (list (list -3 (list "MY_CAE_SHELL_BC" (cons 1005 mainHandle))))))
              (princ (strcat (_T "\n[成功] 已为板壳施加 [" "\n[OK] Shell BC [") scopeTag (_T "] 约束 -> 平动 U:" "] U:") (nth 3 uTriad) " | R:" (nth 3 rTriad)))
            )
          )
        )
        (princ (strcat "\n[错误] 不支持的面片实体类型: " mainType))
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
  (setq ss (ssget '((0 . "MESH,REGION,SURFACE,3DSOLID,3DFACE,LWPOLYLINE,INSERT"))))
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

;;; ---------- 启动 ----------
(vl-load-com)
(register-all-cae-apps)
(lock-vis-layer)
(princ (_T "\n[CAE] 梁+板壳已加载。默认单位: N/mm、N、MPa、弹簧 N/mm 与 Nmm/rad。语言: SETLANG"
           "\n[CAE] Beam+Shell loaded. Defaults: N/mm, N, MPa, spring N/mm & Nmm/rad. Lang: SETLANG"))
(princ (_T "\n  梁载荷: SETLOAD/DELLOAD/SETPTLOAD/DELPTLOAD | 梁约束: SETBC/DELBC/ADDBC | 弹性支撑: SETSPRING/DELSPRING"
           "\n  Beam loads: SETLOAD/DELLOAD/SETPTLOAD/DELPTLOAD | Beam BC: SETBC/DELBC/ADDBC | Spring: SETSPRING/DELSPRING"))
(princ (_T "\n  截面: SETSEC/DELSEC | 板壳: SETSHELLLOAD/DELSHELLLOAD | SETSHELL | ADDSHELLBC/DELSHELLBC"
           "\n  Sec: SETSEC/DELSEC | Shell: SETSHELLLOAD/DELSHELLLOAD | SETSHELL | ADDSHELLBC/DELSHELLBC"))
(princ (_T "\n  显示(梁+板壳): REFRESH_ALL/SETSCALE/TOGGLELOAD/TOGGLEBC/TOGGLESEC"
           "\n  Display(beam+shell): REFRESH_ALL/SETSCALE/TOGGLELOAD/TOGGLEBC/TOGGLESEC"))
(princ)

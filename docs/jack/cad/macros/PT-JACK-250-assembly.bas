Attribute VB_Name = "PT_JACK_Assembly"
'==========================================================================
' PT-JACK-250 — assembly helper
'
' Inserts the eight saved parts into a new assembly AT THE ORIGIN. It does
' NOT position or mate them: each part macro builds its part in its own
' natural orientation (turned parts revolve about X, plate parts extrude
' along Z), so a blind coordinate insert would place them inconsistently.
'
' For a CORRECTLY POSITIONED assembly, open instead:
'     cad/step/PT-JACK-250-assembly.step
' which carries every part at its retracted station. Use this macro only if
' you want to mate the macro-built parts yourself.
'
' Station table for manual positioning (mm along the jack axis, 0 = front
' face of the nose yoke, retracted):
'   yoke0      X =     0.0
'   yoke1      X =    75.0
'   gland0     X =    95.0
'   gland1     X =   170.0
'   tube0      X =   140.0
'   stop0      X =   175.0
'   stop1      X =   215.0
'   pist0      X =   415.0
'   pist1      X =   450.0
'   tube1      X =   450.0
'   beam0      X =   420.0
'   beam1      X =   500.0
'   grip0      X =   465.0
'   grip1      X =   575.0
'   rod0       X =    30.0
'   rod1       X =   450.0
'   cylinder axes at Z = +/- 80
'
' Edit PARTS_DIR below, then run main.
'==========================================================================
Option Explicit

Const PARTS_DIR As String = "C:\PT-JACK-250\parts\"

Dim swApp As Object
Dim swAsm As Object

Private Sub Ins(ByVal fname As String)
    Dim swComp As Object
    swApp.OpenDoc6 PARTS_DIR & fname, 1, 32, "", 0, 0
    Set swComp = swAsm.AddComponent5(PARTS_DIR & fname, 0, "", False, "", 0#, 0#, 0#)
    If swComp Is Nothing Then MsgBox "Could not insert " & fname
End Sub

Sub main()
    Dim tpl As String
    Set swApp = Application.SldWorks
    tpl = swApp.GetUserPreferenceStringValue(10)     'swDefaultTemplateAssembly
    Set swAsm = swApp.NewDocument(tpl, 0, 0, 0)
    If swAsm Is Nothing Then
        MsgBox "No assembly template found."
        Exit Sub
    End If

    Ins "P1-nose-yoke.SLDPRT"
    Ins "P2-crossbeam.SLDPRT"
    Ins "P3-cylinder-tube.SLDPRT"
    Ins "P4-piston-rod.SLDPRT"
    Ins "P5-piston.SLDPRT"
    Ins "P6-gland-cap.SLDPRT"
    Ins "P7-bearing-pad.SLDPRT"
    Ins "P8-gripper-barrel.SLDPRT"
    Ins "P10-stop-ring.SLDPRT"
    swAsm.ForceRebuild3 True
    swAsm.ViewZoomtofit2
    MsgBox "Parts inserted at the origin — mate them using the station table" & vbCrLf & _
           "in this macro's header, or open cad/step/PT-JACK-250-assembly.step" & vbCrLf & _
           "for the positioned assembly." & vbCrLf & vbCrLf & _
           "Overall length: retracted 593.0 mm, extended 793.0 mm."
End Sub

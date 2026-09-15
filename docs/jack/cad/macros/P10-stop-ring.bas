Attribute VB_Name = "P10_stop_ring"
'==========================================================================
' PT-JACK-250  —  Stroke stop spacer ring
'
' Generated from docs/jack/cad/python/gen_sw.py. Units in the API are METRES.
'
' HOW TO RUN
'   1. SolidWorks > Tools > Macro > New...  (save as P10_stop_ring.swp)
'   2. In the VBA editor: File > Import File... and pick this .bas
'   3. Run Sub main
'
' The macro creates a NEW part and builds the feature tree. Late binding is
' used throughout so no type-library reference is required, and reference
' planes are picked by position rather than by name, so it works on any
' language template.
'
' NOT TESTED AGAINST A LIVE SOLIDWORKS INSTALL — see cad/README.md. If a
' call fails, the STEP file of the same part is the fallback.
'==========================================================================
Option Explicit

Dim swApp As Object
Dim swModel As Object

Private Function NewPartDoc() As Object
    Dim tpl As String
    tpl = swApp.GetUserPreferenceStringValue(8)      'swDefaultTemplatePart
    Set NewPartDoc = swApp.NewDocument(tpl, 0, 0, 0)
End Function

Private Function SelectPlane(ByVal idx As Integer) As Boolean
    'idx 1 = Front, 2 = Top, 3 = Right (order is template-independent)
    Dim swFeat As Object, n As Integer
    Set swFeat = swModel.FirstFeature
    n = 0
    Do While Not swFeat Is Nothing
        If swFeat.GetTypeName2 = "RefPlane" Then
            n = n + 1
            If n = idx Then
                SelectPlane = swFeat.Select2(False, 0)
                Exit Function
            End If
        End If
        Set swFeat = swFeat.GetNextFeature
    Loop
    SelectPlane = False
End Function

Private Sub SelectLastFeature()
    Dim swFeat As Object
    Set swFeat = swModel.FeatureByPositionReverse(0)
    swFeat.Select2 False, -1
End Sub

Sub main()
    Set swApp = Application.SldWorks
    Set swModel = NewPartDoc()
    If swModel Is Nothing Then
        MsgBox "No part template found. Set one in Tools > Options > File Locations."
        Exit Sub
    End If

    swModel.ClearSelection2 True
    SelectPlane 1                                  'Front plane
    swModel.SketchManager.InsertSketch True
    swModel.SketchManager.CreateCenterLine -0.010000, 0#, 0#, 0.050000, 0#, 0#
    swModel.SketchManager.CreateLine 0.000000, 0.017000, 0#, 0.040000, 0.017000, 0#
    swModel.SketchManager.CreateLine 0.040000, 0.017000, 0#, 0.040000, 0.024900, 0#
    swModel.SketchManager.CreateLine 0.040000, 0.024900, 0#, 0.000000, 0.024900, 0#
    swModel.SketchManager.CreateLine 0.000000, 0.024900, 0#, 0.000000, 0.017000, 0#
    swModel.SketchManager.InsertSketch True
    swModel.ClearSelection2 True
    SelectLastFeature

    swModel.FeatureManager.FeatureRevolve2 True, True, False, False, False, False, _
        0, 0, 6.28318530717959, 0, False, False, 0, 0, 0, 0, 0, False, True, True

    swModel.ViewZoomtofit2
    swModel.ClearSelection2 True
    MsgBox "Stroke stop spacer ring built. Save as P10_stop_ring.SLDPRT."
End Sub

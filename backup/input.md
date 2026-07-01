Private prevCompany As String

Private Sub Worksheet_Change(ByVal Target As Range)
    If Intersect(Target, Me.Range("B2")) Is Nothing Then Exit Sub
    If Trim(Me.Range("B2").Value) = "" Then Exit Sub

    Application.EnableEvents = False
    On Error GoTo CleanUp
    IngestForTicker
CleanUp:
    Application.EnableEvents = True
End Sub


Private Sub Worksheet_Calculate()
    ' B3 (company name) is a formula = 'Past Years Trend'!C1, changes via recalc.
    Dim cell As Range
    Set cell = Me.Range("B3")
    If IsError(cell.Value) Then Exit Sub
    If IsEmpty(cell.Value) Then Exit Sub

    Dim cur As String
    cur = Trim(CStr(cell.Value))
    If cur = "" Then Exit Sub

    If cur <> prevCompany Then
        prevCompany = cur
        Application.EnableEvents = False
        On Error GoTo CleanUp
        IngestRating
CleanUp:
        Application.EnableEvents = True
    End If
End Sub


Private Sub stumulation_Click()
Dim iteration As Integer
Dim simulation_Sheet As Double
Dim percent As Double
Dim std As Double
Dim column_name As String
Dim column_name_input_value As Double
Dim StartTime As Double
Dim MinutesElapsed As String
Dim MyRange As Range
Dim temp As String
Dim Avg As Double
Dim custom_std As Double
Dim temp2 As Double
Dim c_formula As String
Dim output_column_name As String
Dim output_column_cellnumber As String

    iteration = InputBox("plese enter the number of stumulation you want to make")
    column_name = InputBox("Please select the columns on which you would like to iterate")
    std = InputBox("choose the std")
    output_column_name = LCase(InputBox("choose from vo,co,cr for the output sheet"))

    If (output_column_name = "vo") Then
        output_column_name = "Valuation Output"
        output_column_cellnumber = "B33"
    ElseIf (output_column_name = "co") Then
        output_column_name = "CFO (OI)"
        output_column_cellnumber = "B42"
    ElseIf (output_column_name = "cr") Then
        output_column_name = "CFO (Rev)"
        output_column_cellnumber = "B40"
    Else
        MsgBox ("INVALID DATA, PLEASE SELECT FROM 'vo,co,cr'")
        Exit Sub
    End If

    On Error GoTo CleanUp
    Application.EnableEvents = False

    column_name_input_value = Worksheets("Input sheet").Range(column_name).Value

    StartTime = Timer
    c_formula = Worksheets("Input sheet").Range(column_name).Formula

    Worksheets("simulation_Sheet").Columns(1).ClearContents
    Worksheets("simulation_Sheet").Columns(2).ClearContents
    Worksheets("simulation_Sheet").Columns(3).ClearContents

    For i = 2 To iteration Step 1
        percent = Application.WorksheetFunction.NormInv(Rnd, column_name_input_value, std)
        Worksheets("Input sheet").Range(column_name).Value = percent
        simulation_Sheet = Worksheets(output_column_name).Range(output_column_cellnumber).Value
        Worksheets("simulation_Sheet").Range("A" & i).Value = percent
        Worksheets("simulation_Sheet").Range("B" & i).Value = simulation_Sheet
    Next

    temp = "B2:B" & iteration
    Set MyRange = Worksheets("simulation_Sheet").Range(temp)

    Avg = Application.WorksheetFunction.Average(MyRange)
    custom_std = Application.WorksheetFunction.StDev(MyRange)
    Worksheets("simulation_Sheet").Range("G2").Value = Avg
    Worksheets("simulation_Sheet").Range("G3").Value = custom_std
    Worksheets("simulation_Sheet").Range("G4").Value = Application.WorksheetFunction.Max(MyRange)
    Worksheets("simulation_Sheet").Range("G5").Value = Application.WorksheetFunction.Min(MyRange)

    For i = 2 To iteration Step 1
        temp2 = Worksheets("simulation_Sheet").Range("B" & i).Value
        Worksheets("simulation_Sheet").Range("C" & i).Value = Application.WorksheetFunction.Norm_Dist(temp2, Avg, custom_std, False)
    Next

    Worksheets("simulation_Sheet").Range("I2").Value = iteration
    Worksheets("simulation_Sheet").Range("I5").Value = std
    Worksheets("simulation_Sheet").Range("I4").Value = column_name
    Worksheets("simulation_Sheet").Range("I6").Value = output_column_name
    MinutesElapsed = Round(Timer - StartTime, 2)
    Worksheets("simulation_Sheet").Range("I3").Value = MinutesElapsed
    Worksheets("Input sheet").Range(column_name).Formula = c_formula
    Worksheets("simulation_Sheet").Range("A1").Value = "Sample Input"
    Worksheets("simulation_Sheet").Range("B1").Value = "Sample Output"
    Worksheets("simulation_Sheet").Range("C1").Value = "Normal Distribution"

CleanUp:
    Application.EnableEvents = True
End Sub

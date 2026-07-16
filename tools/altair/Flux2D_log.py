#! Flux2D 25.1
loadProject('C:/Users/eruku/Akshith/REGO/Altair/Problem1.FLU')

startMacroTransaction()
Scenario['CHANGE_AIRGAP'].CSVFilename='Magentic_field.csv'
endMacroTransaction()

closeProject()

exit()

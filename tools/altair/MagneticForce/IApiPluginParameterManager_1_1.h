#ifndef IAPIPLUGINPARAMETERMANAGER_1_1_H
#define IAPIPLUGINPARAMETERMANAGER_1_1_H

#include "IApi.h"
#include "IApiPluginParameterManager_1_0.h"
#include <limits>

namespace NApiHelpersV3_4_0
{
    class CSimpleString;
}


namespace NApiCore
{
    /** This class is the interface for the API plugin parameters dialog feature.
    *
    * 1_1 implements the ability to give the dialog a custom title, 
    * and implements functionality for adding the following parameter types:
    *  - integer, string, combo box and tables
    */
    class IApiPluginParameterManager_1_1 : public IApiPluginParameterManager_1_0
    {
    public:
        IApiPluginParameterManager_1_1() {};

        virtual ~IApiPluginParameterManager_1_1() {};
        
        /**
        * Adds a new integer to the current group with the option to limit the range of values that can be entered
        * @param defaultValue the default integer value to add
        * @param name The name of the field
        * @param min The minimum numeric value that can be entered in this field
        * @param max The maximum numeric value that can be entered in this field
        */
        virtual void addIntegerValue(int defaultValue,
                                     const NApiHelpersV3_4_0::CSimpleString& name,
                                     int min = std::numeric_limits<int>::lowest(),
                                     int max = std::numeric_limits<int>::max()) = 0;

        /**
        * Adds a new double to the current group with the option to pass in a recommended range of values
        * @param defaultValue the default double value to add
        * @param name The name of the field
        * @param unit The units of the field (one of NApi::EPluginPropertyUnitTypes)
        * @param min The minimum recommended value, below which any number entered will be displayed in red
        * @param max The maximum recommended value, above which any number entered will be displayed in red
        */
        virtual void addDoubleValue(double defaultValue,
                                    const NApiHelpersV3_4_0::CSimpleString& name,
                                    NApi::EPluginPropertyUnitTypes unit = NApi::EPluginPropertyUnitTypes::eNone,
                                    double min = std::numeric_limits<double>::lowest(),
                                    double max = std::numeric_limits<double>::max()) = 0;

        /**
        * Adds a new combo box to the current group
        * @param defaultValue the default string value to be selected, is added to the combo box
        * @param name The name of the field
        */
        virtual void addComboBoxValue(NApiHelpersV3_4_0::CSimpleString defaultValue, const NApiHelpersV3_4_0::CSimpleString& name) = 0;

        /**
        * Adds a new option to the combo box in the current group
        * @param comboBoxOption the string value to be added to the combo box
        * @param name The name of the field to add the option too
        */
        virtual void addComboBoxOption(NApiHelpersV3_4_0::CSimpleString comboBoxOption, const NApiHelpersV3_4_0::CSimpleString& name) = 0;

        /**
        * Adds an editable string field
        * @param defaultValue the default string value for the column
        * @param name The name of the field
        */
        virtual void addStringValue(NApiHelpersV3_4_0::CSimpleString defaultValue, const NApiHelpersV3_4_0::CSimpleString& name) = 0;

        //
        // value access handlers

        /**
        * Opens an existing list group to get values, using ID to allow iteration.
        * @param groupId The ID of the group
        * @param (out) elementName The name of the first element used in the list, passed empty and filled for plugins to store
        */
        virtual void openListGroup(const int groupId, NApiHelpersV3_4_0::CSimpleString& elementName) = 0;

        /**
        * Retrieves a integer from the current group
        * @param name The name of the field to retrieve the data from
        * @return value of the field, if unattainable returns -1
        */
        virtual int getIntegerValue(const NApiHelpersV3_4_0::CSimpleString& name) const = 0;

        /**
        * Retrieves a integer from the current group
        * @param name The name of the field to retrieve the data from
        * @return value of the field, if unattainable returns an empty string
        */
        virtual NApiHelpersV3_4_0::CSimpleString getComboBoxValue(const NApiHelpersV3_4_0::CSimpleString& name) const = 0;

        /** @param name title to use for parameter dialog */
        virtual void setParametersDialogTitle(const NApiHelpersV3_4_0::CSimpleString& name) {};

        /**
        * @param name The name of the field to retrieve the data from
        * @return string value of the field, if unattainable returns ""
        */
        virtual NApiHelpersV3_4_0::CSimpleString getStringValue(const NApiHelpersV3_4_0::CSimpleString& name) const = 0;

        // --
        // Double and bool overloads to use simplestring type

        /**
        * Adds a new boolean to the current group
        * @param defaultValue the default boolean value to add
        * @param name The name of the field
        */
        virtual void addBoolValue(bool defaultValue, const NApiHelpersV3_4_0::CSimpleString& name) = 0;

        /**
        * Retrieves a double from the current group
        * @param name The name of the field to retrieve the data from
        * @return value of the field, if unattainable returns -1.79769e+308 (std::numeric_limits<double>::lowest())
        */
        virtual double getDoubleValue(const NApiHelpersV3_4_0::CSimpleString& name) const = 0;

        /**
        * Retrieves a boolean from the current group
        * @param name The name of the field to retrieve the data from
        * @return value of the field, if unattainable returns false
        */
        virtual bool getBoolValue(const NApiHelpersV3_4_0::CSimpleString& name) const = 0;

        // --
        // group handling overloads to use simplestring type

        /**
        * Adds a new group to add values
        * @param name The name of the group
        */
        virtual void startGroup(const NApiHelpersV3_4_0::CSimpleString& name) = 0;

        /**
        * Opens an existing group to get values
        * @param name The name of the group
        */
        virtual void openGroup(const NApiHelpersV3_4_0::CSimpleString& name) = 0;

        /**
        * Opens an existing Interaction group to get values, using ID to allow iteration.
        * @param groupId The ID of the group
        * @param (out) interactionName The name of the interaction, passed empty and filled for plugins to store
        */
        virtual void openInteractionGroup(const int groupId, NApiHelpersV3_4_0::CSimpleString& interactionName) = 0;

        /**
        * Opens an existing Interaction group to get values, using ID to allow iteration.
        * @param groupId The ID of the group
        * @param (out) material1Name The name of the first material used in the interaction, passed empty and filled for plugins to store
        * @param (out) material2Name The name of the second material used in the interaction, passed empty and filled for plugins to store
        */
        virtual void openInteractionGroup(const int groupId, NApiHelpersV3_4_0::CSimpleString& material1Name, NApiHelpersV3_4_0::CSimpleString& material2Name) = 0;

        //
        // table specific handlers

        /**
        * Adds a new table. 
        * Add column descriptors with eg addTableDoubleColumnHeader().
        * Create a row using startTableRow(), then add entries using
        * the usual eg addDoubleValue 
        * note: please name these fields to match the column names.
        * Close rows with endTableRow(), and the table with endTable().
        *
        * @param name The name of the table
        */
        virtual void startTable(const char name[NApi::FILE_PATH_MAX_LENGTH]) = 0;

        /**
         * Sets the header data for a double column for a table
        * @param defaultValue value that is set when a row is added
        * @param name table column name to use
        * @param unit the unit type to use for the column
        */
        virtual void addTableDoubleColumnHeader(double defaultValue, const NApiHelpersV3_4_0::CSimpleString& name, NApi::EPluginPropertyUnitTypes unit = NApi::EPluginPropertyUnitTypes::eNone) = 0;

        /**
         * Sets the header data for a string column for a table
        * @param defaultValue value that is set when a row is added
        * @param name table column name to use
        * @param unit the unit type to use for the column
        */
        virtual void addTableStringColumnHeader(const NApiHelpersV3_4_0::CSimpleString& defaultValue, const NApiHelpersV3_4_0::CSimpleString& name) = 0;

        /**
         * Sets the header data for an int column for a table
        * @param defaultValue value that is set when a row is added
        * @param name table column name to use
        * @param unit the unit type to use for the column
        */
        virtual void addTableIntColumnHeader(int defaultValue, const NApiHelpersV3_4_0::CSimpleString& name) = 0;

        /**
         * Sets the header data for a boolean column for a table
        * @param defaultValue value that is set when a row is added
        * @param name table column name to use
        * @param unit the unit type to use for the column
        */
        virtual void addTableBoolColumnHeader(bool defaultValue, const NApiHelpersV3_4_0::CSimpleString& name) = 0;

        /**
        * Opens an existing table to get values
        * @param name The name of the table
        */
        virtual void openTable(const char name[NApi::FILE_PATH_MAX_LENGTH]) = 0;

        /**
        * Adds a new row
        * Add entries for the row using the usual eg addDoubleValue
        * note: please name these fields to match the column names.
        */
        virtual void startTableRow() = 0;

        /**
        * Opens an existing table row to provide access to column values
        * @param row the index of the row
        */
        virtual void openTableRow(const int row) = 0;

        /** closes the current row */
        virtual void endTableRow() = 0;

        /** @return number of rows in the current table, 0 if not table */
        virtual size_t getTableRowCount() const = 0;

        /** closes the current table */
        virtual void endTable() = 0;

    public:
        // importing base overloads
        using IApiPluginParameterManager_1_0::openInteractionGroup;
        using IApiPluginParameterManager_1_0::addDoubleValue;
        using IApiPluginParameterManager_1_0::getDoubleValue;
        using IApiPluginParameterManager_1_0::addBoolValue;
        using IApiPluginParameterManager_1_0::getBoolValue;

    protected:
        /** Unversioned API Manager */
        CApiManager* m_apiManager = nullptr;
    };
}

#endif

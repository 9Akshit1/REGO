#ifndef ICUSTOMPROPERTYDATAAPI_1_0_H
#define ICUSTOMPROPERTYDATAAPI_1_0_H

#include "IApi.h"

namespace NApiCore
{
    /**
     * The ICustomPropertyDataApi_1_0 interface provides basic access to the
     * custom property data and in read/write mode to storage for delta
     * values.
     *
     * NAME:     Custom Property Data
     * ID:       EApiId::eCustomPropertyData (8)
     * VERSION:  1.0
     */
    class ICustomPropertyDataApi_1_0 : public IApi
    {
    public:
        /**
         * Constructor, does nothing.
         */
        ICustomPropertyDataApi_1_0() {};

        /**
         * Destructor, does nothing.
         */
        virtual ~ICustomPropertyDataApi_1_0() {};

        /**
         * Retrieves a ICustomPropertyManager interface
         * instance corresponding to the custom property manager
         * that defines the custom property data for this instance
         *
         * The Custom Property Data instance is free to return any minor
         * revision equal to or later than the specified value, as long as
         * the major revision matches.
         *
         *
         * @param major The required major version
         * @param minor The minimum required minor version
         * @return An initialised API instance or 0 if none
         */
        virtual IApi* getManager(NApi::tApiMajorVersion major,
                                 NApi::tApiMinorVersion minor) = 0;

        /**
         * Returns a pointer to the stored data for the supplied
         * property.  Property index values can be retrieved from a
         * manager instance.
         *
         * Data is returned as a pointer to the first element of
         * an array of values of length equal to the number of elements
         * property of the corresponding properties meta-data.
         *
         * @param index The index of the property
         * @return Pointer to start of data or 0 if no such property
         */
        virtual const double* getValue(unsigned int index) = 0;

        /**
         * Returns a pointer to the stored data for the supplied
         * property.
         *
         * Data is returned as a pointer to the first element of
         * an array of values of length equal to the number of elements
         * property of the corresponding properties meta-data.
         *
         * @param name The name of the property
         * @return Pointer to start of data or 0 if no such property
         */
        virtual const double* getValue(const char* name) = 0;

        /**
         * Returns a pointer to the stored delta data for the supplied
         * property.  Property index values can be retrieved from a
         * manager instance.
         *
         * Data is returned as a pointer to the first element of
         * an array of values of length equal to the number of elements
         * property of the corresponding properties meta-data.
         *
         * @param index The index of the property
         * @return Pointer to start of data or 0 if no such property or
         *         the API is in read only mode
         */
        virtual double* getDelta(unsigned int index) = 0;

        /**
         * Returns a pointer to the stored delta data for the supplied
         * property.
         *
         * Data is returned as a pointer to the first element of
         * an array of values of length equal to the number of elements
         * property of the corresponding properties meta-data.
         *
         * @param name The name of the property
         * @return Pointer to start of data or 0 if no such property or
         *         the API is in read only mode
         */
        virtual double* getDelta(const char* name) = 0;

        /**
         * Returns a boolean to indicate if live data and delta
         * values are available for the supplied property. Property
         * index values can be retrieved from a manager instance.
         *
         * In read only mode this method returns true if there is
         * live data for the property.  you can guarantee that
         * future calls to getValue for the property will not return
         * 0.
         *
         * In read/write mode this method returns true if there is
         * live data and delta values for the property.  you can guarantee
         * that future calls to getValue and getDelta for the property
         * will not return 0.
         *
         * @param index The index of the property
         * @return true if live values (and in read/write delta values)
         *         are present for the property
         */
        virtual bool hasData(unsigned int index) = 0;

        /**
         * Returns a boolean to indicate if live data and delta
         * values are available for the supplied property.
         *
         * In read only mode this method returns true if there is
         * live data for the property.  you can guarantee that
         * future calls to getValue for the property will not return
         * 0.
         *
         * In read/write mode this method returns true if there is
         * live data and delta values for the property.  you can guarantee
         * that future calls to getValue and getDelta for the property
         * will not return 0.
         *
         * Property index values can be retrieved from a
         * manager instance.
         *
         * @param name The name of the property
         * @return true if live values (and in read/write delta values)
         *         are present for the property
         */
        virtual bool hasData(const char* name) = 0;
    };
};

#endif // ICUSTOMPROPERTYDATAAPI_1_0_H

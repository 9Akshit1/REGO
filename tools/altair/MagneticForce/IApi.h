#ifndef IAPI_H
#define IAPI_H

#include "ApiTypes.h"
#include "ApiIds.h"

/**
 * The NApiCore namespace encompasses all interface declarations
 * for the supported APIs and their various supported versions.
 *
 * All API instances are based on the IApi interface which provides
 * common methods to all APIs.
 *
 * Two types of API are then defined:
 *
 * Base APIs - Providing access to top level areas of EDEM
 * such as the field manager or geometry manager.
 *
 * Sub APIs - Providing access to individual data elements such
 * as a specific field data instance or geometry group.
 *
 * Each API consists of a number of public interfaces of differing
 * major and minor version numbers (e.g. IFieldApi_1_0, IFieldApi_1_1,
 * IFieldApi_2_0).  Minor revisions are only allowed to add new functions
 * and not change the definitions of earlier versions.  All minor
 * versions derive from the immediately previous versions interface
 * (e.g. IFieldApi_1_1 derives from IFieldApi_1_0).  Major revisions are
 * complete re-workings of the interface.  The X.0 version of an
 * interface stands alone and does not derive from any previous version.
 *
 * The API Manager is responsible for the creation and initialization
 * of base APIs.  Sub APIs are created by a corresponding base API.
 * (e.g IFieldApi_?_? instances are created by IFieldManager_?_?)
 */
namespace NApiCore
{
    /**
     * IApi is the base class for all API implementations
     * supported by EDEM.  It provides a number of common
     * methods used to identify an instance and to query
     * its state.
     *
     * API instances can be in either Read/Write or Read only
     * mode and may toggle between the two at different times.
     *
     * For example, an API providing the ability to add, delete or
     * configure field data would be read only during the processing
     * of contacts and particle body forces, but may be Read/Write
     * elsewhere.
     */
    class IApi
    {
    public:
        /**
         * Constructor, does nothing.
         */
        IApi() {};

        /**
         * Destructor, does nothing.
         */
        virtual ~IApi() {};

        /**
         * Returns the version of the API instance.
         *
         * @param major
         *        [RETURN VALUE]
         *        Value to be set with the major version number
         * @param minor
         *        [RETURN VALUE]
         *        Value to be set with the minor version number
         */
        virtual void getApiVersion(NApi::tApiMajorVersion& major,
                                   NApi::tApiMinorVersion& minor) = 0;

        /**
         * Returns the API id.
         *
         * @return The API id
         */
        virtual EApiId getApiId() const = 0;

        /**
         * Returns a bool to say if this API is in read only
         * mode.  Any methods that attempt to change the
         * system state will fail if the API is in read only
         * mode.
         *
         * @return true if the API is in read only mode
         */
        virtual bool readOnly() const = 0;
    };
};

#endif // IAPI_H

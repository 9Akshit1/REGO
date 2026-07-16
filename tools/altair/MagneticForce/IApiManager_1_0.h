#ifndef IAPIMANAGER_1_0_H
#define IAPIMANAGER_1_0_H

#include "ApiTypes.h"
#include "IApi.h"

namespace NApiCore
{
    /**
     * The API manager provides the ability to allocate and initialise
     * various APIs for use by plugins.
     *
     * NAME:    API Manager
     * ID:      EApiId::eApiManager (0)
     * VERSION: 1.0
     *
     * All allocation and de-allocation of API instances is handled
     * by the manager.
     *
     * getApi() is used for retrieving allocated and initialized
     * base API instances.
     *
     * NOTE: The API manager is capable of returning instances of
     * any supported version of the API manager.
     */
    class IApiManager_1_0 : public IApi
    {
    public:
        /**
         * Constructor, does nothing.
         */
        IApiManager_1_0() {};

        /**
         * Destructor, does nothing.
         */
        virtual ~IApiManager_1_0() {};

        /**
         * Retrieves a base API instance for use.
         *
         * The Api manager is free to return any minor revision
         * equal to or later than the specified value, as long as the
         * major revision matches.
         *
         * @param apiId The id of the API
         * @param major The major version of the API you wish
         * @param minor The minor version of the API you wish
         * @return An initialised API instance or 0 if none
         */
        virtual IApi* getApi(EApiId                 apiId,
                             NApi::tApiMajorVersion major,
                             NApi::tApiMinorVersion minor) = 0;

        /**
         * WARNING: DEPRECATED
         * 
         * This currently has no effect but previously it used to:
         * 
         * Release an API instance back to the manager
         * for potential re-use or de-allocation.
         * @param apiInstance The instance to release
         */
        virtual void release(IApi* apiInstance) = 0;
    };
};

#endif // IAPIMANAGER_1_0_H
